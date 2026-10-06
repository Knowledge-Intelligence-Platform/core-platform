"""FastAPI entry point and direct Phase 1 service composition."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Annotated, cast
from urllib.parse import parse_qs
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.agent import PlatformKnowledgeAgent, public_answer
from app.config import Settings, get_settings
from app.knowledge_base import KnowledgeBase, KnowledgeBaseUnavailableError
from app.models import (
    HealthResponse,
    KnowledgeQueryResponse,
    QueryRequest,
    ReadyResponse,
    SyncJob,
)
from app.slack import (
    FeedbackStore,
    SlackIntegration,
)
from app.tasks import (
    KnowledgeTasks,
    TaskDecision,
    TaskError,
    TaskRecord,
    TaskStore,
)

LOGGER = logging.getLogger(__name__)


STANDARD_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, value in record.__dict__.items():
            if name in STANDARD_RECORD_FIELDS or name.startswith("_"):
                continue
            if isinstance(value, str | int | float | bool) or value is None:
                payload[name] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


@dataclass
class Application:
    settings: Settings
    agent: PlatformKnowledgeAgent
    knowledge_base: KnowledgeBase
    slack: SlackIntegration | None
    reindex_lock: Lock
    tasks: KnowledgeTasks | None = None


def build_application(settings: Settings) -> Application:
    knowledge_base = KnowledgeBase(
        region=settings.aws_region,
        knowledge_base_id=settings.knowledge_base_id,
        data_source_id=settings.knowledge_base_data_source_id,
    )
    agent = PlatformKnowledgeAgent(
        model_id=settings.bedrock_model_id,
        platform_name=settings.platform_name,
        search=knowledge_base,
        maximum_results=settings.agent_max_search_results,
        conversation_window=settings.slack_conversation_window,
        metrics_enabled=settings.metrics_enabled,
        stream_interval_seconds=settings.slack_stream_interval_seconds,
        summarization_enabled=settings.conversation_summarization_enabled,
        summary_ratio=settings.conversation_summary_ratio,
        preserve_recent_messages=settings.conversation_preserve_recent_messages,
        session_persistence_enabled=settings.session_persistence_enabled,
        session_bucket=settings.s3_bucket,
        session_prefix=settings.session_prefix,
        aws_region=settings.aws_region,
        max_tokens=settings.bedrock_max_tokens,
        prompt_caching_enabled=settings.bedrock_prompt_caching_enabled,
    )
    slack = (
        SlackIntegration(
            bot_token=settings.slack_bot_token.get_secret_value(),
            signing_secret=settings.slack_signing_secret.get_secret_value(),
            agent=agent,
            maximum_message_length=settings.slack_max_message_length,
            streaming_enabled=settings.slack_streaming_enabled,
            require_identity=True,
            feedback_store=FeedbackStore(
                region=settings.aws_region,
                bucket=settings.s3_bucket,
                prefix=settings.feedback_prefix,
            ),
        )
        if settings.slack_enabled
        else None
    )
    return Application(
        settings=settings,
        agent=agent,
        knowledge_base=knowledge_base,
        slack=slack,
        reindex_lock=Lock(),
        tasks=KnowledgeTasks(
            knowledge_base=knowledge_base,
            store=TaskStore(
                bucket=settings.s3_bucket, prefix=settings.task_prefix, region=settings.aws_region
            ),
            region=settings.aws_region,
        )
        if settings.tasks_enabled
        else None,
    )


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    current = build_application(get_settings())
    fastapi_app.state.application = current
    try:
        yield
    finally:
        current.knowledge_base.close()
        if current.tasks is not None:
            current.tasks.store.close()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        started = monotonic()
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        LOGGER.info(
            "Request completed.",
            extra={
                "correlation_id": correlation_id,
                "operation": f"{request.method} {request.url.path}",
                "component": "api",
                "duration_ms": round((monotonic() - started) * 1_000, 2),
            },
        )
        return response


app = FastAPI(
    title="Knowledge Intelligence",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(RequestLoggingMiddleware)
bearer_scheme = HTTPBearer(auto_error=False)


def application(request: Request) -> Application:
    return cast(Application, request.app.state.application)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="healthy")


@app.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse:
    current = application(request)
    reachable = current.knowledge_base.reachable()
    if not reachable:
        raise HTTPException(status_code=503, detail="Knowledge base is unavailable.")
    return ReadyResponse(status="ready", knowledge_base_reachable=True)


@app.post("/knowledge/query", response_model=KnowledgeQueryResponse)
def query(
    payload: QueryRequest,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> KnowledgeQueryResponse:
    current = application(request)
    authorization = (
        f"{credentials.scheme} {credentials.credentials}" if credentials is not None else None
    )
    user_id = _query_identity(current.settings, authorization)
    result = current.agent.answer(
        payload.prompt,
        conversation_id=payload.conversation_id,
        user_id=user_id,
    )
    return KnowledgeQueryResponse(answer=public_answer(result.answer))


def _query_identity(settings: Settings, authorization: str | None) -> str:
    if not settings.query_tokens:
        raise HTTPException(status_code=503, detail="Query authentication is not configured.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="A valid bearer token is required.")
    for email, expected in settings.query_tokens.items():
        if secrets.compare_digest(token.encode(), expected.get_secret_value().encode()):
            return email
    raise HTTPException(status_code=401, detail="A valid bearer token is required.")


def _task_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[KnowledgeTasks, str]:
    current = application(request)
    authorization = (
        f"{credentials.scheme} {credentials.credentials}" if credentials is not None else None
    )
    owner = _query_identity(current.settings, authorization)
    if current.tasks is None:
        raise HTTPException(status_code=503, detail="Task operations are not enabled.")
    if owner not in current.settings.task_allowed_identities:
        raise HTTPException(status_code=403, detail="This identity cannot operate knowledge tasks.")
    return current.tasks, owner


@app.get("/tasks/source", tags=["Knowledge tasks"])
def task_source(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> dict[str, object]:
    tasks, _ = _task_access(request, credentials)
    return tasks.knowledge_base.source_status()


@app.post("/tasks/sync/{task_id}", response_model=TaskRecord, tags=["Knowledge tasks"])
def propose_sync(
    task_id: UUID,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> TaskRecord:
    tasks, owner = _task_access(request, credentials)
    return tasks.propose(owner, task_id)


@app.get("/tasks/{task_id}", response_model=TaskRecord, tags=["Knowledge tasks"])
def get_task(
    task_id: UUID,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> TaskRecord:
    tasks, owner = _task_access(request, credentials)
    return tasks.get(owner, task_id)


@app.post("/tasks/{task_id}/decision", response_model=TaskRecord, tags=["Knowledge tasks"])
def decide_task(
    task_id: UUID,
    payload: TaskDecision,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> TaskRecord:
    tasks, owner = _task_access(request, credentials)
    return tasks.decide(owner, task_id, payload.decision)


@app.post("/tasks/{task_id}/resume", response_model=TaskRecord, tags=["Knowledge tasks"])
def resume_task(
    task_id: UUID,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> TaskRecord:
    tasks, owner = _task_access(request, credentials)
    return tasks.resume(owner, task_id)


@app.exception_handler(TaskError)
async def task_error(request: Request, error: TaskError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.post("/admin/reindex", response_model=SyncJob, status_code=202)
def reindex(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> SyncJob:
    current = application(request)
    configured = current.settings.admin_token.get_secret_value()
    if not configured:
        raise HTTPException(status_code=503, detail="Administrative reindexing is not configured.")
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, configured):
        raise HTTPException(status_code=401, detail="Invalid administrative credentials.")
    if not current.reindex_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A reindex operation is already running.")
    try:
        return current.knowledge_base.run()
    finally:
        current.reindex_lock.release()


def _ephemeral(text: str) -> JSONResponse:
    return JSONResponse({"response_type": "ephemeral", "text": text})


def _no_commands() -> JSONResponse:
    """Slash commands were removed; asking in words is the only way in."""
    return _ephemeral(
        "No commands needed \u2014 just mention me or send me a message, and ask in your own words."
    )


def _handle_interaction(
    current: Application,
    form: dict[str, list[str]],
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    if current.slack is None:
        raise HTTPException(status_code=503, detail="Slack integration is not enabled.")
    try:
        interaction = json.loads(form.get("payload", [""])[0])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack interaction payload.") from exc
    if not isinstance(interaction, dict):
        raise HTTPException(status_code=400, detail="Invalid Slack interaction payload.")
    action = current.slack.parse_action(interaction)
    if action is None:
        return JSONResponse({"ok": True})
    if action.kind == "followup" and action.channel and action.thread_ts and action.question:
        background_tasks.add_task(
            current.slack.process,
            action.channel,
            action.thread_ts,
            action.question,
            requester_id=action.user_id,
        )
    elif action.kind == "feedback":
        background_tasks.add_task(current.slack.feedback_store.record, action)
    return JSONResponse({"ok": True})


def _handle_event(
    current: Application,
    body: bytes,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    if current.slack is None:
        raise HTTPException(status_code=503, detail="Slack integration is not enabled.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack event payload.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Slack event payload.")
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge")})
    event_id = payload.get("event_id")
    event = payload.get("event")
    if not isinstance(event_id, str) or not isinstance(event, dict):
        return JSONResponse({"ok": True})
    if not current.slack.accept(event_id) or event.get("bot_id"):
        return JSONResponse({"ok": True})
    supported = event.get("type") == "app_mention" or (
        event.get("type") == "message" and event.get("channel_type") == "im"
    )
    channel, text, message_ts = event.get("channel"), event.get("text"), event.get("ts")
    if (
        supported
        and isinstance(channel, str)
        and channel
        and isinstance(text, str)
        and text
        and isinstance(message_ts, str)
        and message_ts
    ):
        thread_ts = event.get("thread_ts") or message_ts
        if not isinstance(thread_ts, str):
            thread_ts = message_ts
        requester_id = event.get("user")
        background_tasks.add_task(
            current.slack.process,
            channel,
            thread_ts,
            text,
            requester_id=requester_id if isinstance(requester_id, str) else None,
        )
    return JSONResponse({"ok": True})


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    current = application(request)
    if current.slack is None:
        raise HTTPException(status_code=503, detail="Slack integration is not enabled.")
    body = await request.body()
    if not current.slack.verify(
        body,
        request.headers.get("X-Slack-Request-Timestamp"),
        request.headers.get("X-Slack-Signature"),
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.")
    if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        return _handle_event(current, body, background_tasks)
    form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    if form.get("command", [""])[0]:
        return _no_commands()
    return _handle_interaction(current, form, background_tasks)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", "")
    LOGGER.exception(
        "Unhandled request failure.",
        extra={
            "correlation_id": correlation_id,
            "operation": f"{request.method} {request.url.path}",
            "component": "api",
        },
    )
    # Error responses bypass the logging middleware, so echo the id here too.
    return JSONResponse(
        status_code=500,
        content={"message": "The request could not be completed."},
        headers={"X-Correlation-ID": correlation_id} if correlation_id else None,
    )


@app.exception_handler(KnowledgeBaseUnavailableError)
async def knowledge_unavailable(
    request: Request, error: KnowledgeBaseUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"message": "The knowledge service is temporarily unavailable."},
    )

"""FastAPI entry point and direct Phase 1 service composition."""

from __future__ import annotations

import json
import logging
import re
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import cast
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.agent import PlatformKnowledgeAgent, public_answer
from app.appconfig import AppConfigReader
from app.config import Settings, get_settings
from app.coverage import Coverage, coverage, is_coverage_request
from app.diagram_analysis import DiagramAnalyzer
from app.embeddings import Embeddings
from app.github_reader import GitHubReader
from app.ingestion import Ingestion
from app.models import (
    HealthResponse,
    KnowledgeQueryResponse,
    QueryRequest,
    ReadyResponse,
    ReindexSummary,
)
from app.registry import ComponentRegistry, load_registry
from app.s3_reader import S3Reader
from app.search import HybridSearch
from app.slack import (
    DiagramStore,
    FeedbackStore,
    SlackIntegration,
    mention_question,
)
from app.vector_store import VectorStore

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
    registry: ComponentRegistry
    agent: PlatformKnowledgeAgent
    search: HybridSearch
    ingestion: Ingestion
    vector_store_reachable: bool
    slack: SlackIntegration | None
    reindex_lock: Lock


def _registry_sources(
    settings: Settings, source: S3Reader
) -> tuple[tuple[str, Callable[[str], str]], ...]:
    """Every place this tenant's registry may be read from, best first.

    All of them belong to the tenant being deployed, so a failure degrades to
    that tenant's own older data and never to anyone else's.
    """
    sources: list[tuple[str, Callable[[str], str]]] = []
    if settings.registry_appconfig_application:
        sources.append(
            (
                "appconfig",
                AppConfigReader(
                    region=settings.aws_region,
                    application=settings.registry_appconfig_application,
                    environment=settings.registry_appconfig_environment,
                    profile=settings.registry_appconfig_profile,
                ).read_text,
            )
        )
    if settings.registry_document_key:
        sources.append(("s3", source.read_text))
        sources.append(("s3-previous-version", source.read_previous_text))
    return tuple(sources)


def build_application(settings: Settings) -> Application:
    source = S3Reader(
        settings.aws_region,
        settings.s3_bucket,
        settings.max_document_size_bytes,
    )
    registry = load_registry(
        directory=settings.registry_directory,
        document_key=settings.registry_document_key,
        cache_path=settings.registry_cache_path,
        sources=_registry_sources(settings, source),
    )
    embeddings = Embeddings(
        settings.openai_api_key.get_secret_value(),
        settings.embedding_model,
        settings.embedding_dimensions,
    )
    vectors = VectorStore(
        region=settings.aws_region,
        source_bucket=settings.s3_bucket,
        vector_bucket=settings.vector_bucket_name,
        index_name=settings.vector_index_name,
        dimensions=settings.embedding_dimensions,
    )
    search = HybridSearch(embeddings, vectors, settings.vector_top_k)
    try:
        search.replace_keyword_cache(vectors.load_chunks())
    except RuntimeError:
        LOGGER.exception(
            "Keyword search cache could not be restored.",
            extra={"operation": "restore_keyword_cache", "component": "search"},
        )
    agent = PlatformKnowledgeAgent(
        api_key=settings.openai_api_key.get_secret_value(),
        model_id=settings.openai_model,
        platform_name=registry.root.name,
        search=search,
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
    )
    github = (
        GitHubReader(
            settings.github_token.get_secret_value(),
            settings.github_api_url,
        )
        if settings.github_enabled
        else None
    )
    ingestion = Ingestion(
        s3=source,
        github=github,
        registry=registry,
        embeddings=embeddings,
        vectors=vectors,
        search=search,
        s3_prefix=settings.s3_prefix,
        batch_size=settings.embedding_batch_size,
        ingest_unmapped_documents=settings.ingest_unmapped_documents,
        diagram_analyzer=(
            DiagramAnalyzer(
                api_key=settings.openai_api_key.get_secret_value(),
                model_id=settings.visual_analysis_model or settings.openai_model,
                render_dpi=settings.visual_render_dpi,
                maximum_pages=settings.visual_max_pages_per_document,
            )
            if settings.visual_analysis_enabled
            else None
        ),
    )
    slack = (
        SlackIntegration(
            bot_token=settings.slack_bot_token.get_secret_value(),
            signing_secret=settings.slack_signing_secret.get_secret_value(),
            agent=agent,
            maximum_message_length=settings.slack_max_message_length,
            streaming_enabled=settings.slack_streaming_enabled,
            feedback_store=FeedbackStore(
                region=settings.aws_region,
                bucket=settings.s3_bucket,
                prefix=settings.feedback_prefix,
            ),
            diagram_store=DiagramStore(
                region=settings.aws_region,
                bucket=settings.s3_bucket,
                prefix=settings.diagram_prefix,
                base_url=settings.public_base_url,
            ),
        )
        if settings.slack_enabled
        else None
    )
    return Application(
        settings=settings,
        registry=registry,
        agent=agent,
        search=search,
        ingestion=ingestion,
        vector_store_reachable=vectors.reachable(),
        slack=slack,
        reindex_lock=Lock(),
    )


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    fastapi_app.state.application = build_application(get_settings())
    yield
    application: Application = fastapi_app.state.application
    if application.ingestion.github:
        application.ingestion.github.close()
    application.ingestion.vectors.close()


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


def application(request: Request) -> Application:
    return cast(Application, request.app.state.application)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="healthy")


@app.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse:
    current = application(request)
    return ReadyResponse(
        status="ready" if current.vector_store_reachable else "not_ready",
        vector_store_reachable=current.vector_store_reachable,
        cached_chunks=current.search.cached_chunk_count,
    )


DIAGRAM_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@app.api_route("/diagrams/{diagram_id}.png", methods=["GET", "HEAD"])
def diagram(diagram_id: str, request: Request) -> Response:
    current = application(request)
    if current.slack is None or current.slack.diagram_store is None:
        raise HTTPException(status_code=404, detail="Not found.")
    if not DIAGRAM_ID.fullmatch(diagram_id):
        raise HTTPException(status_code=404, detail="Not found.")
    image = current.slack.diagram_store.read(diagram_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@app.post("/knowledge/query", response_model=KnowledgeQueryResponse)
def query(payload: QueryRequest, request: Request) -> KnowledgeQueryResponse:
    result = application(request).agent.answer(
        payload.prompt,
        conversation_id=payload.conversation_id,
    )
    return KnowledgeQueryResponse(answer=public_answer(result.answer))


@app.post("/admin/reindex", response_model=ReindexSummary)
def reindex(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> ReindexSummary:
    current = application(request)
    configured = current.settings.admin_token.get_secret_value()
    if not configured:
        raise HTTPException(
            status_code=503, detail="Administrative reindexing is not configured."
        )
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, configured):
        raise HTTPException(
            status_code=401, detail="Invalid administrative credentials."
        )
    if not current.reindex_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="A reindex operation is already running."
        )
    try:
        result = current.ingestion.run()
        current.vector_store_reachable = True
        return result
    finally:
        current.reindex_lock.release()


def _ephemeral(text: str) -> JSONResponse:
    return JSONResponse({"response_type": "ephemeral", "text": text})


def _no_commands() -> JSONResponse:
    """Slash commands were removed; asking in words is the only way in."""
    return _ephemeral(
        "No commands needed \u2014 just mention me or send me a message, "
        "and ask in your own words."
    )


def _coverage(current: Application) -> Coverage:
    return coverage(current.registry, current.search.cached_chunks())


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
        raise HTTPException(
            status_code=400, detail="Invalid Slack interaction payload."
        ) from exc
    if not isinstance(interaction, dict):
        raise HTTPException(
            status_code=400, detail="Invalid Slack interaction payload."
        )
    action = current.slack.parse_action(interaction)
    if action is None:
        return JSONResponse({"ok": True})
    if (
        action.kind == "followup"
        and action.channel
        and action.thread_ts
        and action.question
    ):
        background_tasks.add_task(
            current.slack.process,
            action.channel,
            action.thread_ts,
            action.question,
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
        raise HTTPException(
            status_code=400, detail="Invalid Slack event payload."
        ) from exc
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
        if is_coverage_request(mention_question(text)):
            background_tasks.add_task(
                current.slack.post_coverage, channel, thread_ts, _coverage(current)
            )
        else:
            background_tasks.add_task(current.slack.process, channel, thread_ts, text)
    return JSONResponse({"ok": True})


@app.post("/slack/events")
async def slack_events(
    request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
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
    if not request.headers.get("content-type", "").startswith(
        "application/x-www-form-urlencoded"
    ):
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

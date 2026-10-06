"""The HTTP surface, driven through the real app with stubbed collaborators."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.knowledge_base import KnowledgeBase, KnowledgeBaseUnavailableError
from app.models import KnowledgeAnswer, SyncJob
from app.slack import SlackAction
from app.tasks import KnowledgeTasks, TaskError, TaskStore

ADMIN_TOKEN = "s3cret-admin-token"
FORM = {"content-type": "application/x-www-form-urlencoded"}
APPROVER = {"Authorization": "Bearer approver-token"}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []


class StubAgent:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    def answer(
        self, question: str, *, conversation_id: str | None = None, user_id: str | None = None
    ) -> KnowledgeAnswer:
        self.recorder.calls.append(("answer", question, conversation_id, user_id))
        return KnowledgeAnswer(answer=f"Use the cluster [S1] guide. {question}")


class ExplodingAgent:
    def answer(
        self, question: str, *, conversation_id: str | None = None, user_id: str | None = None
    ) -> KnowledgeAnswer:
        raise RuntimeError("internal detail that must not leak")


class StubSlack:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.valid = True
        self.seen: set[str] = set()
        self.feedback_store = self

    def verify(self, body: bytes, timestamp: str | None, signature: str | None) -> bool:
        return self.valid

    def accept(self, event_id: str) -> bool:
        if event_id in self.seen:
            return False
        self.seen.add(event_id)
        return True

    def process(
        self, channel: str, thread_ts: str, text: str, *, requester_id: str | None = None
    ) -> None:
        self.recorder.calls.append(("process", channel, thread_ts, text))

    def record(self, action: SlackAction) -> None:
        self.recorder.calls.append(("feedback", action.rating))

    def parse_action(self, payload: dict[str, object]) -> SlackAction | None:
        actions = payload.get("actions")
        if not isinstance(actions, list) or not actions:
            return None
        first = actions[0]
        assert isinstance(first, dict)
        action_id = str(first.get("action_id", ""))
        if action_id.startswith("knowledge_followup_"):
            return SlackAction(
                kind="followup", channel="C1", thread_ts="1.0", question=str(first.get("value"))
            )
        if action_id.startswith("knowledge_feedback_"):
            return SlackAction(
                kind="feedback", answer_id="a", response_type="general", rating="helpful"
            )
        return None


class StubKnowledgeBase:
    def reachable(self) -> bool:
        return True

    def close(self) -> None:
        return None

    def run(self) -> SyncJob:
        return SyncJob(
            knowledge_base_id="ABCDEFGHIJ",
            data_source_id="KLMNOPQRST",
            ingestion_job_id="1234567890",
            status="STARTING",
        )


class StubSettings:
    class _Secret:
        def __init__(self, value: str) -> None:
            self.value = value

        def get_secret_value(self) -> str:
            return self.value

    admin_token = _Secret(ADMIN_TOKEN)
    query_tokens = {"reader@example.com": _Secret("reader-token")}


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def slack(recorder: Recorder) -> StubSlack:
    return StubSlack(recorder)


@pytest.fixture
def client(recorder: Recorder, slack: StubSlack) -> Iterator[TestClient]:
    main.app.state.application = main.Application(
        settings=StubSettings(),  # type: ignore[arg-type]
        agent=StubAgent(recorder),  # type: ignore[arg-type]
        knowledge_base=cast(KnowledgeBase, StubKnowledgeBase()),
        slack=slack,  # type: ignore[arg-type]
        reindex_lock=threading.Lock(),
    )
    yield TestClient(main.app, headers={"Authorization": "Bearer reader-token"})
    main.app.state.application = None


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "healthy"}


def test_ready_reports_knowledge_base_state(client: TestClient) -> None:
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    assert body["knowledge_base_reachable"] is True


def test_query_returns_only_the_answer(client: TestClient) -> None:
    body = client.post("/knowledge/query", json={"prompt": "What is KIP Service?"}).json()
    assert set(body) == {"answer"}


def test_query_strips_internal_source_markers(client: TestClient) -> None:
    body = client.post("/knowledge/query", json={"prompt": "What is KIP Service?"}).json()
    assert "[S1]" not in body["answer"]


def test_query_rejects_a_too_short_prompt(client: TestClient) -> None:
    assert client.post("/knowledge/query", json={"prompt": "a"}).status_code == 422


def test_query_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/knowledge/query", json={"prompt": "hello there", "extra": 1})
    assert response.status_code == 422


def test_conversation_id_is_forwarded(client: TestClient, recorder: Recorder) -> None:
    client.post("/knowledge/query", json={"prompt": "follow up", "conversation_id": "abc"})
    assert recorder.calls[-1] == ("answer", "follow up", "abc", "reader@example.com")


@pytest.mark.parametrize(
    ("headers", "expected"),
    [({}, 401), ({"X-Admin-Token": "wrong"}, 401), ({"X-Admin-Token": ADMIN_TOKEN}, 202)],
)
def test_reindex_requires_the_admin_token(
    client: TestClient, headers: dict[str, str], expected: int
) -> None:
    assert client.post("/admin/reindex", headers=headers).status_code == expected


def test_slack_rejects_a_bad_signature(client: TestClient, slack: StubSlack) -> None:
    slack.valid = False
    assert client.post("/slack/events", content=b"{}").status_code == 401


def test_slack_url_verification_echoes_the_challenge(client: TestClient) -> None:
    response = client.post("/slack/events", json={"type": "url_verification", "challenge": "abc"})
    assert response.json() == {"challenge": "abc"}


def test_app_mention_is_dispatched(client: TestClient, recorder: Recorder) -> None:
    event = {"type": "app_mention", "channel": "C9", "text": "hi", "ts": "111.1"}
    client.post("/slack/events", json={"event_id": "E1", "event": event})
    assert ("process", "C9", "111.1", "hi") in recorder.calls


def test_a_mentioned_coverage_question_never_reaches_the_agent(
    client: TestClient, recorder: Recorder
) -> None:
    event = {
        "type": "app_mention",
        "channel": "C9",
        "text": "<@U123> what do you know",
        "ts": "111.2",
    }
    client.post("/slack/events", json={"event_id": "E9", "event": event})

    assert ("process", "C9", "111.2", "<@U123> what do you know") in recorder.calls
    assert not any(call[0] == "answer" for call in recorder.calls)


def test_a_mentioned_ordinary_question_still_reaches_the_agent(
    client: TestClient, recorder: Recorder
) -> None:
    event = {
        "type": "app_mention",
        "channel": "C9",
        "text": "<@U123> how do I onboard",
        "ts": "111.3",
    }
    client.post("/slack/events", json={"event_id": "E10", "event": event})

    assert not any(call[0] == "coverage" for call in recorder.calls)
    assert any(call[0] == "process" for call in recorder.calls)


def test_duplicate_events_are_ignored(client: TestClient, recorder: Recorder) -> None:
    event = {"type": "app_mention", "channel": "C9", "text": "hi", "ts": "111.1"}
    client.post("/slack/events", json={"event_id": "E2", "event": event})
    recorder.calls.clear()
    client.post("/slack/events", json={"event_id": "E2", "event": event})
    assert recorder.calls == []


def test_bot_messages_are_ignored(client: TestClient, recorder: Recorder) -> None:
    event = {"type": "app_mention", "channel": "C9", "text": "hi", "ts": "1.1", "bot_id": "B1"}
    client.post("/slack/events", json={"event_id": "E3", "event": event})
    assert recorder.calls == []


def test_malformed_event_payload_is_rejected(client: TestClient) -> None:
    assert client.post("/slack/events", content=b"{oops").status_code == 400


def test_followup_button_continues_the_thread(client: TestClient, recorder: Recorder) -> None:
    payload = json.dumps({"actions": [{"action_id": "knowledge_followup_1", "value": "Next?"}]})
    client.post("/slack/events", headers=FORM, content=f"payload={payload}")
    assert any(call[0] == "process" for call in recorder.calls)


def test_feedback_button_is_recorded(client: TestClient, recorder: Recorder) -> None:
    payload = json.dumps({"actions": [{"action_id": "knowledge_feedback_1", "value": "a:g:h"}]})
    client.post("/slack/events", headers=FORM, content=f"payload={payload}")
    assert ("feedback", "helpful") in recorder.calls


def test_unknown_interaction_is_ignored(client: TestClient, recorder: Recorder) -> None:
    payload = json.dumps({"actions": [{"action_id": "unknown", "value": "x"}]})
    response = client.post("/slack/events", headers=FORM, content=f"payload={payload}")
    assert response.json() == {"ok": True}
    assert recorder.calls == []


def test_unhandled_errors_return_a_safe_message(recorder: Recorder, slack: StubSlack) -> None:
    main.app.state.application = main.Application(
        settings=StubSettings(),  # type: ignore[arg-type]
        agent=ExplodingAgent(),  # type: ignore[arg-type]
        knowledge_base=cast(KnowledgeBase, StubKnowledgeBase()),
        slack=slack,  # type: ignore[arg-type]
        reindex_lock=threading.Lock(),
    )
    safe = TestClient(
        main.app,
        raise_server_exceptions=False,
        headers={"Authorization": "Bearer reader-token"},
    )
    response = safe.post("/knowledge/query", json={"prompt": "trigger failure"})
    assert response.status_code == 500
    assert response.json() == {"message": "The request could not be completed."}
    assert "internal detail" not in response.text
    assert "X-Correlation-ID" in response.headers
    main.app.state.application = None


def test_a_slash_command_is_redirected_to_natural_language(
    client: TestClient, recorder: Recorder
) -> None:
    body = "command=/ask-kip&text=What is KIP&response_url=https://hooks.slack.com/x"
    payload = client.post("/slack/events", headers=FORM, content=body).json()

    assert payload["response_type"] == "ephemeral"
    assert "mention me" in payload["text"]
    assert recorder.calls == []


@pytest.mark.parametrize("authorization", ["", "Basic reader-token", "Bearer wrong-token"])
def test_query_rejects_unverified_identity(
    client: TestClient, recorder: Recorder, authorization: str
) -> None:
    response = client.post(
        "/knowledge/query",
        json={"prompt": "What is the platform?"},
        headers={"Authorization": authorization},
    )
    assert response.status_code == 401
    assert recorder.calls == []


def test_request_body_cannot_select_another_identity(
    client: TestClient, recorder: Recorder
) -> None:
    response = client.post(
        "/knowledge/query",
        json={"prompt": "What is the platform?", "user_id": "administrator@example.com"},
    )
    assert response.status_code == 422
    assert recorder.calls == []


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.writes = 0
        self.fail_next_write = False

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {"Contents": [{"Key": key} for key in self.objects if key == kwargs["Prefix"]]}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body, etag = self.objects[kwargs["Key"]]
        return {"Body": BytesIO(body), "ETag": etag}

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        if self.fail_next_write:
            self.fail_next_write = False
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "PutObject")
        previous = self.objects.get(kwargs["Key"])
        if (kwargs.get("IfNoneMatch") == "*" and previous is not None) or (
            "IfMatch" in kwargs and (previous is None or previous[1] != kwargs["IfMatch"])
        ):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.writes += 1
        etag = f'"{self.writes}"'
        self.objects[kwargs["Key"]] = (kwargs["Body"], etag)
        return {"ETag": etag}


class TaskKnowledgeBase(StubKnowledgeBase):
    knowledge_base_id = "ABCDEFGHIJ"
    data_source_id = "KLMNOPQRST"

    def __init__(self) -> None:
        self.tokens: list[str | None] = []
        self.fail_next_start = False
        self.job_status = "COMPLETE"

    def run(self, *, client_token: str | None = None) -> SyncJob:
        self.tokens.append(client_token)
        if self.fail_next_start:
            self.fail_next_start = False
            raise KnowledgeBaseUnavailableError("Start response was lost.")
        return super().run()

    def sync_status(self, job_id: str) -> SyncJob:
        return super().run().model_copy(update={"status": self.job_status})

    def source_status(self) -> dict[str, object]:
        return {"source_status": "AVAILABLE", "latest_job": None}


@pytest.fixture
def task_service(client: TestClient) -> tuple[KnowledgeTasks, TaskKnowledgeBase, MemoryS3]:
    backend = TaskKnowledgeBase()
    storage = MemoryS3()
    tasks = KnowledgeTasks(
        knowledge_base=cast(Any, backend),
        store=TaskStore(
            bucket="test-tasks", prefix="tasks", region="us-east-1", client=cast(Any, storage)
        ),
        region="us-east-1",
        approvers=frozenset({"approver@example.com"}),
    )
    main.app.state.application.settings = Settings(
        _env_file=None,
        knowledge_base_id="ABCDEFGHIJ",
        knowledge_base_data_source_id="KLMNOPQRST",
        s3_bucket="test-tasks",
        tasks_enabled=True,
        query_tokens={
            "reader@example.com": "reader-token",
            "other@example.com": "other-token",
            "viewer@example.com": "viewer-token",
            "approver@example.com": "approver-token",
        },
        task_allowed_identities={"reader@example.com", "other@example.com"},
        task_approver_identities={"approver@example.com"},
    )
    main.app.state.application.tasks = tasks
    return tasks, backend, storage


def test_sync_task_requires_explicit_approval(client: TestClient, task_service) -> None:
    _, backend, _ = task_service
    task_id = str(uuid4())
    proposal = client.post(f"/tasks/sync/{task_id}")
    assert proposal.status_code == 200
    assert proposal.json()["status"] == "awaiting_approval"
    assert client.post(f"/tasks/{task_id}/resume").status_code == 409
    assert backend.tokens == []
    decision = client.post(
        f"/tasks/{task_id}/decision", headers=APPROVER, json={"decision": "approve"}
    )
    assert decision.json()["status"] == "approved"
    assert backend.tokens == []
    started = client.post(f"/tasks/{task_id}/resume")
    assert started.json()["status"] == "running"
    assert decision.json()["decided_by"] == "approver@example.com"
    completed = client.post(f"/tasks/{task_id}/resume")
    assert completed.json()["status"] == "complete"
    assert client.post(f"/tasks/{task_id}/resume").json()["status"] == "complete"
    assert len(backend.tokens) == 1


@pytest.mark.parametrize("token,status", [("wrong", 401), ("viewer-token", 403)])
def test_knowledge_access_does_not_grant_task_access(client, task_service, token, status) -> None:
    result = client.post(f"/tasks/sync/{uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == status
    assert task_service[1].tokens == []


def test_tasks_are_disabled_by_default(client: TestClient) -> None:
    assert client.get("/tasks/source").status_code == 503


def test_task_owner_is_enforced(client: TestClient, task_service) -> None:
    task_id = str(uuid4())
    client.post(f"/tasks/sync/{task_id}")
    other = {"Authorization": "Bearer other-token"}
    assert client.get(f"/tasks/{task_id}", headers=other).status_code == 404
    assert (
        client.post(
            f"/tasks/{task_id}/decision", headers=other, json={"decision": "approve"}
        ).status_code
        == 404
    )
    assert client.post(f"/tasks/{task_id}/resume", headers=other).status_code == 404


def test_rejected_task_never_starts(client: TestClient, task_service) -> None:
    task_id = str(uuid4())
    client.post(f"/tasks/sync/{task_id}")
    client.post(f"/tasks/{task_id}/decision", headers=APPROVER, json={"decision": "reject"})
    assert client.post(f"/tasks/{task_id}/resume").json()["status"] == "rejected"
    assert (
        client.post(
            f"/tasks/{task_id}/decision", headers=APPROVER, json={"decision": "approve"}
        ).status_code
        == 409
    )
    assert task_service[1].tokens == []


def test_proposal_retries_preserve_the_same_task(client: TestClient, task_service) -> None:
    task_id = str(uuid4())
    first = client.post(f"/tasks/sync/{task_id}").json()
    second = client.post(f"/tasks/sync/{task_id}").json()
    assert first == second
    assert task_service[2].writes == 1


@pytest.mark.parametrize("approved", [False, True])
def test_expired_approval_cannot_start(client: TestClient, task_service, approved: bool) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    if approved:
        tasks.decide("approver@example.com", task_id, "approve")
    record, etag = tasks.store.load(task_id)
    tasks.store.save(
        record.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
        etag,
    )
    if not approved:
        assert (
            client.post(
                f"/tasks/{task_id}/decision", headers=APPROVER, json={"decision": "approve"}
            ).status_code
            == 409
        )
    assert client.post(f"/tasks/{task_id}/resume").status_code == 409
    assert backend.tokens == []


def test_uncertain_start_reuses_token_after_restart(client: TestClient, task_service) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    backend.fail_next_start = True
    assert client.post(f"/tasks/{task_id}/resume").status_code == 503
    assert tasks.get("reader@example.com", task_id).status == "starting"
    restarted = KnowledgeTasks(
        knowledge_base=cast(Any, backend),
        store=tasks.store,
        region="us-east-1",
        approvers=tasks.approvers,
    )
    assert restarted.resume("reader@example.com", task_id).status == "running"
    assert len(backend.tokens) == 2
    assert backend.tokens[0] == backend.tokens[1]
    assert len(backend.tokens[0]) == 64


def test_state_is_persisted_before_aws_start(client: TestClient, task_service) -> None:
    tasks, backend, storage = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    storage.fail_next_write = True
    assert client.post(f"/tasks/{task_id}/resume").status_code == 503
    assert backend.tokens == []


def test_concurrent_decision_cannot_overwrite_state(task_service) -> None:
    tasks, _, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    stale, etag = tasks.store.load(task_id)
    tasks.decide("approver@example.com", task_id, "reject")
    with pytest.raises(TaskError, match="concurrently"):
        tasks.store.save(stale.model_copy(update={"status": "approved"}), etag)
    assert tasks.get("reader@example.com", task_id).status == "rejected"


def test_changed_target_invalidates_approval(task_service) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    backend.data_source_id = "UVWXYZ1234"
    with pytest.raises(TaskError, match="target"):
        tasks.resume("reader@example.com", task_id)
    assert backend.tokens == []


@pytest.mark.parametrize(
    "status,expected",
    [
        ("COMPLETE", "complete"),
        ("FAILED", "failed"),
        ("STOPPED", "stopped"),
        ("IN_PROGRESS", "running"),
    ],
)
def test_sync_completion_reflects_aws(task_service, status, expected) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    tasks.resume("reader@example.com", task_id)
    backend.job_status = status
    assert tasks.resume("reader@example.com", task_id).status == expected


def test_live_source_status_does_not_start_a_sync(client: TestClient, task_service) -> None:
    assert client.get("/tasks/source").json()["source_status"] == "AVAILABLE"
    assert task_service[1].tokens == []


def test_record_failure_after_start_keeps_recovery_token(task_service, monkeypatch) -> None:
    tasks, backend, storage = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    original = backend.run

    def start_then_lose_storage(*, client_token=None):
        job = original(client_token=client_token)
        storage.fail_next_write = True
        return job

    monkeypatch.setattr(backend, "run", start_then_lose_storage)
    with pytest.raises(TaskError, match="storage"):
        tasks.resume("reader@example.com", task_id)
    assert tasks.get("reader@example.com", task_id).status == "starting"
    monkeypatch.setattr(backend, "run", original)
    assert tasks.resume("reader@example.com", task_id).status == "running"
    assert backend.tokens[0] == backend.tokens[1]


def test_old_uncertain_start_requires_reconciliation(task_service) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    record, etag = tasks.store.load(task_id)
    tasks.store.save(
        record.model_copy(
            update={
                "status": "starting",
                "execution_started_at": datetime.now(UTC) - timedelta(minutes=11),
            }
        ),
        etag,
    )
    with pytest.raises(TaskError, match="reconcile"):
        tasks.resume("reader@example.com", task_id)
    assert backend.tokens == []


def test_operator_revocation_blocks_existing_task(client: TestClient, task_service) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    tasks.propose("reader@example.com", task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    main.app.state.application.settings.task_allowed_identities = {"other@example.com"}
    assert client.post(f"/tasks/{task_id}/resume").status_code == 403
    assert backend.tokens == []


def test_enabled_tasks_require_explicit_operators() -> None:
    with pytest.raises(ValueError, match="Tasks require"):
        Settings(_env_file=None, knowledge_base_id="ABCDEFGHIJ", tasks_enabled=True)


def test_requester_cannot_approve_their_own_task(client: TestClient, task_service) -> None:
    tasks, backend, _ = task_service
    task_id = uuid4()
    client.post(f"/tasks/sync/{task_id}")
    decision = client.post(f"/tasks/{task_id}/decision", json={"decision": "approve"})
    assert decision.status_code == 403
    assert tasks.get("reader@example.com", task_id).status == "awaiting_approval"
    assert backend.tokens == []


def test_approver_cannot_request_tasks(client: TestClient, task_service) -> None:
    assert client.post(f"/tasks/sync/{uuid4()}", headers=APPROVER).status_code == 403


def test_task_id_cannot_be_claimed_by_another_requester(client: TestClient, task_service) -> None:
    task_id = uuid4()
    client.post(f"/tasks/sync/{task_id}")
    claimed = client.post(f"/tasks/sync/{task_id}", headers={"Authorization": "Bearer other-token"})
    assert claimed.status_code == 409
    assert task_service[0].get("reader@example.com", task_id).requester == "reader@example.com"


@pytest.mark.parametrize("approvers", [set(), {"reader@example.com"}, {"unknown@example.com"}])
def test_enabled_tasks_require_an_independent_approver(approvers: set[str]) -> None:
    with pytest.raises(ValueError, match="approver"):
        Settings(
            _env_file=None,
            knowledge_base_id="ABCDEFGHIJ",
            knowledge_base_data_source_id="KLMNOPQRST",
            s3_bucket="test-tasks",
            tasks_enabled=True,
            query_tokens={"reader@example.com": "reader-token"},
            task_allowed_identities={"reader@example.com"},
            task_approver_identities=approvers,
        )

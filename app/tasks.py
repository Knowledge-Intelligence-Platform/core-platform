from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict

from app.evidence import EvidenceRef

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

    from app.actions import ActionHandler
    from app.audit import AuditLog
    from app.policy import TaskPolicy

LOGGER = logging.getLogger(__name__)
TaskStatus = Literal[
    "awaiting_approval",
    "approved",
    "rejected",
    "starting",
    "running",
    "complete",
    "failed",
    "stopped",
]
TERMINAL_STATUSES = {"complete", "failed", "stopped", "rejected"}
APPROVAL_WINDOW = timedelta(hours=1)
UNCERTAIN_START_AFTER = timedelta(minutes=10)


class TaskError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


class TaskOrigin(BaseModel):
    """What started a task. Authority comes from configuration, never from the trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["user", "schedule", "aws_event", "github_event"]
    identity: str
    source_event_id: str | None = None


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str
    target: str
    effect: str
    cites: tuple[EvidenceRef, ...] = ()


class TaskRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    task_type: str
    origin: TaskOrigin
    correlation_id: UUID
    scope: dict[str, str]
    effect: str
    plan: tuple[PlanStep, ...]
    status: TaskStatus = "awaiting_approval"
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None = None
    decided_by: str | None = None
    execution_started_at: datetime | None = None
    result: dict[str, str] | None = None

    @property
    def requester(self) -> str:
        return self.origin.identity


class TaskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]


class TaskStore:
    def __init__(
        self, *, bucket: str, prefix: str, region: str, client: S3Client | None = None
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client(
            "s3",
            region_name=region,
            config=Config(connect_timeout=5, read_timeout=15, retries={"mode": "standard"}),
        )

    def _key(self, task_id: UUID) -> str:
        return f"{self.prefix}/{task_id}.json"

    def load(self, task_id: UUID) -> tuple[TaskRecord, str]:
        try:
            key = self._key(task_id)
            objects = self.client.list_objects_v2(Bucket=self.bucket, Prefix=key, MaxKeys=1)
            if not any(item.get("Key") == key for item in objects.get("Contents", [])):
                raise TaskError("Task not found.", 404)
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                record = TaskRecord.model_validate_json(body.read())
            finally:
                body.close()
            return record, response["ETag"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                raise TaskError("Task not found.", 404) from None
            raise TaskError("Task storage is unavailable.", 503) from None
        except BotoCoreError:
            raise TaskError("Task storage is unavailable.", 503) from None

    def save(self, record: TaskRecord, etag: str | None = None) -> str:
        try:
            if etag is None:
                response = self.client.put_object(
                    Bucket=self.bucket,
                    Key=self._key(record.task_id),
                    Body=record.model_dump_json().encode(),
                    ContentType="application/json",
                    IfNoneMatch="*",
                )
            else:
                response = self.client.put_object(
                    Bucket=self.bucket,
                    Key=self._key(record.task_id),
                    Body=record.model_dump_json().encode(),
                    ContentType="application/json",
                    IfMatch=etag,
                )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
                "412",
                "409",
            }:
                raise TaskError("Task changed concurrently. Reload it before retrying.") from None
            raise TaskError("Task storage is unavailable.", 503) from None
        except BotoCoreError:
            raise TaskError("Task storage is unavailable.", 503) from None
        LOGGER.info(
            "Task state persisted.",
            extra={"component": "tasks", "task_id": str(record.task_id), "status": record.status},
        )
        return response["ETag"]

    def close(self) -> None:
        self.client.close()


class TaskService:
    def __init__(
        self,
        *,
        handlers: Sequence[ActionHandler],
        store: TaskStore,
        audit: AuditLog,
        policy: TaskPolicy,
    ) -> None:
        self.handlers = {handler.task_type: handler for handler in handlers}
        self.store = store
        self.audit = audit
        self.policy = policy

    def _handler(self, task_type: str) -> ActionHandler:
        handler = self.handlers.get(task_type)
        if handler is None:
            raise TaskError("This task type is not enabled.", 404)
        return handler

    def _load(self, identity: str, task_id: UUID) -> tuple[TaskRecord, str]:
        record, etag = self.store.load(task_id)
        if record.task_id != task_id or not self.policy.can_view(identity, record):
            raise TaskError("Task not found.", 404)
        if record.scope != self._handler(record.task_type).scope():
            raise TaskError("Task target no longer matches this deployment. Create a new task.")
        return record, etag

    def _record_event(self, record: TaskRecord, event: str, actor: str) -> None:
        self.audit.record(
            task_id=record.task_id,
            correlation_id=record.correlation_id,
            event=event,
            actor=actor,
            details={"task_type": record.task_type, "status": record.status},
        )

    def get(self, identity: str, task_id: UUID) -> TaskRecord:
        return self._load(identity, task_id)[0]

    def propose(self, task_type: str, origin: TaskOrigin, task_id: UUID) -> TaskRecord:
        handler = self._handler(task_type)
        try:
            existing, _ = self.store.load(task_id)
        except TaskError as exc:
            if exc.status_code != 404:
                raise
        else:
            if existing.requester != origin.identity:
                raise TaskError("This task ID is already in use. Choose a new task ID.")
            return self.get(origin.identity, task_id)
        now = datetime.now(UTC)
        plan = handler.plan()
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            origin=origin,
            correlation_id=uuid4(),
            scope=handler.scope(),
            effect=" ".join(step.effect for step in plan),
            plan=plan,
            status="awaiting_approval" if handler.requires_approval else "approved",
            created_at=now,
            expires_at=now + APPROVAL_WINDOW,
            approved_at=None if handler.requires_approval else now,
            decided_by=None if handler.requires_approval else "policy",
        )
        self._record_event(record, "proposed", origin.identity)
        self.store.save(record)
        return record

    def decide(
        self, approver: str, task_id: UUID, decision: Literal["approve", "reject"]
    ) -> TaskRecord:
        record, etag = self._load(approver, task_id)
        self.policy.check_decision(approver, record)
        target = "approved" if decision == "approve" else "rejected"
        if record.status == target:
            return record
        if record.status != "awaiting_approval":
            raise TaskError("Only a pending proposal can be approved or rejected.")
        if datetime.now(UTC) >= record.expires_at:
            raise TaskError("This proposal expired. Create and review a new task.")
        record = record.model_copy(
            update={
                "status": target,
                "approved_at": datetime.now(UTC) if decision == "approve" else None,
                "decided_by": approver,
            }
        )
        self._record_event(record, target, approver)
        self.store.save(record, etag)
        return record

    def resume(self, identity: str, task_id: UUID) -> TaskRecord:
        record, etag = self._load(identity, task_id)
        if record.status in TERMINAL_STATUSES:
            return record
        if record.status == "awaiting_approval":
            raise TaskError("Explicit approval is required before starting this task.")
        handler = self._handler(record.task_type)
        if record.status == "approved":
            if datetime.now(UTC) >= record.expires_at:
                raise TaskError("This approval expired. Create and review a new task.")
            record = record.model_copy(
                update={"status": "starting", "execution_started_at": datetime.now(UTC)}
            )
            self._record_event(record, "starting", identity)
            etag = self.store.save(record, etag)
        if record.status == "starting":
            if (
                record.execution_started_at is None
                or datetime.now(UTC) - record.execution_started_at > UNCERTAIN_START_AFTER
            ):
                raise TaskError(
                    "Start outcome is uncertain. An operator must reconcile the AWS job."
                )
            outcome = handler.start(record)
        else:
            outcome = handler.poll(record)
        previous = record.status
        record = record.model_copy(update={"status": outcome.status, "result": outcome.result})
        if record.status != previous:
            self._record_event(record, record.status, identity)
        self.store.save(record, etag)
        return record

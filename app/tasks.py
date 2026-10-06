from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict

from app.knowledge_base import KnowledgeBase
from app.models import SyncJob

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

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


class TaskError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


class TaskRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    action: Literal["sync_knowledge_source"] = "sync_knowledge_source"
    requester: str
    region: str
    knowledge_base_id: str
    data_source_id: str
    effect: str = "Start ingestion of published content from the configured knowledge source."
    status: TaskStatus = "awaiting_approval"
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None = None
    decided_by: str | None = None
    execution_started_at: datetime | None = None
    job: SyncJob | None = None


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


class KnowledgeTasks:
    def __init__(
        self,
        *,
        knowledge_base: KnowledgeBase,
        store: TaskStore,
        region: str,
        approvers: frozenset[str],
    ) -> None:
        self.knowledge_base = knowledge_base
        self.store = store
        self.region = region
        self.approvers = approvers

    def _load(self, identity: str, task_id: UUID) -> tuple[TaskRecord, str]:
        record, etag = self.store.load(task_id)
        if identity != record.requester and identity not in self.approvers:
            raise TaskError("Task not found.", 404)
        if (
            record.task_id != task_id
            or record.region != self.region
            or record.knowledge_base_id != self.knowledge_base.knowledge_base_id
            or record.data_source_id != self.knowledge_base.data_source_id
        ):
            raise TaskError("Task target no longer matches this deployment. Create a new task.")
        return record, etag

    def get(self, identity: str, task_id: UUID) -> TaskRecord:
        return self._load(identity, task_id)[0]

    def propose(self, requester: str, task_id: UUID) -> TaskRecord:
        try:
            existing, _ = self.store.load(task_id)
        except TaskError as exc:
            if exc.status_code != 404:
                raise
        else:
            if existing.requester != requester:
                raise TaskError("This task ID is already in use. Choose a new task ID.")
            return self.get(requester, task_id)
        now = datetime.now(UTC)
        record = TaskRecord(
            task_id=task_id,
            requester=requester,
            region=self.region,
            knowledge_base_id=self.knowledge_base.knowledge_base_id,
            data_source_id=self.knowledge_base.data_source_id,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        self.store.save(record)
        return record

    def decide(
        self, approver: str, task_id: UUID, decision: Literal["approve", "reject"]
    ) -> TaskRecord:
        record, etag = self._load(approver, task_id)
        if approver not in self.approvers:
            raise TaskError("This identity cannot decide knowledge tasks.", 403)
        if approver == record.requester:
            raise TaskError("A requester cannot decide their own task.", 403)
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
        self.store.save(record, etag)
        return record

    def resume(self, identity: str, task_id: UUID) -> TaskRecord:
        record, etag = self._load(identity, task_id)
        if record.status in {"complete", "failed", "stopped", "rejected"}:
            return record
        if record.status == "awaiting_approval":
            raise TaskError("Explicit approval is required before starting this task.")
        if record.status == "approved":
            if datetime.now(UTC) >= record.expires_at:
                raise TaskError("This approval expired. Create and review a new task.")
            record = record.model_copy(
                update={
                    "status": "starting",
                    "execution_started_at": datetime.now(UTC),
                }
            )
            etag = self.store.save(record, etag)
        if record.status == "starting":
            if record.execution_started_at is None or datetime.now(
                UTC
            ) - record.execution_started_at > timedelta(minutes=10):
                raise TaskError(
                    "Start outcome is uncertain. An operator must reconcile the AWS job."
                )
            token = hashlib.sha256(
                f"{record.requester}:{self.region}:{record.knowledge_base_id}:"
                f"{record.data_source_id}:{task_id}".encode()
            ).hexdigest()
            job = self.knowledge_base.run(client_token=token)
        else:
            if record.job is None:
                raise TaskError("Task has no recorded ingestion job.")
            job = self.knowledge_base.sync_status(record.job.ingestion_job_id)
        terminal_states: dict[str, TaskStatus] = {
            "COMPLETE": "complete",
            "FAILED": "failed",
            "STOPPED": "stopped",
        }
        status = terminal_states.get(job.status, "running")
        record = record.model_copy(update={"status": status, "job": job})
        self.store.save(record, etag)
        return record

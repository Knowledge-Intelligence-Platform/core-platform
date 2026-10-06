from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.tasks import TaskError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

LOGGER = logging.getLogger(__name__)
ALREADY_RECORDED = {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}


class AuditLog:
    """Append-only task events: one create-only object per task and event.

    Details must be identifiers and states, never document text or credentials.
    """

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

    def record(
        self,
        *,
        task_id: UUID,
        correlation_id: UUID,
        event: str,
        actor: str,
        details: Mapping[str, str] | None = None,
    ) -> None:
        body = {
            "task_id": str(task_id),
            "correlation_id": str(correlation_id),
            "event": event,
            "actor": actor,
            "at": datetime.now(UTC).isoformat(),
            "details": dict(details or {}),
        }
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=f"{self.prefix}/{task_id}/{event}.json",
                Body=json.dumps(body, separators=(",", ":")).encode(),
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ALREADY_RECORDED:
                return
            raise TaskError("Task audit storage is unavailable.", 503) from None
        except BotoCoreError:
            raise TaskError("Task audit storage is unavailable.", 503) from None
        LOGGER.info(
            "Task audit event recorded.",
            extra={"component": "audit", "task_id": str(task_id), "event": event},
        )

    def close(self) -> None:
        self.client.close()

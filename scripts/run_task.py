"""Executor entry point: run one approved task to a terminal state.

Step Functions starts this as a separate ECS task with the executor IAM role.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from uuid import UUID

from app.actions.sync_knowledge import SyncKnowledgeSource
from app.audit import AuditLog
from app.config import Settings, get_settings
from app.knowledge_base import KnowledgeBase
from app.policy import TaskPolicy
from app.tasks import TERMINAL_STATUSES, LocalRunner, TaskRecord, TaskService, TaskStore

LOGGER = logging.getLogger("scripts.run_task")


def build_service(settings: Settings) -> TaskService:
    knowledge_base = KnowledgeBase(
        region=settings.aws_region,
        knowledge_base_id=settings.knowledge_base_id,
        data_source_id=settings.knowledge_base_data_source_id,
    )
    return TaskService(
        handlers=[SyncKnowledgeSource(knowledge_base=knowledge_base, region=settings.aws_region)],
        store=TaskStore(
            bucket=settings.s3_bucket, prefix=settings.task_prefix, region=settings.aws_region
        ),
        audit=AuditLog(
            bucket=settings.s3_bucket, prefix=settings.audit_prefix, region=settings.aws_region
        ),
        policy=TaskPolicy(approvers=frozenset()),
        runner=LocalRunner(),
    )


def run(
    service: TaskService,
    task_id: UUID,
    *,
    poll_seconds: float,
    timeout_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> TaskRecord:
    deadline = clock() + timeout_seconds
    while True:
        record = service.execute(task_id)
        if record.status in TERMINAL_STATUSES:
            return record
        if clock() >= deadline:
            raise TimeoutError("The task did not reach a terminal state in time.")
        sleep(poll_seconds)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if len(argv) != 2:
        print("Usage: python -m scripts.run_task <task-id>", file=sys.stderr)
        return 2
    settings = get_settings()
    record = run(
        build_service(settings),
        UUID(argv[1]),
        poll_seconds=settings.executor_poll_seconds,
        timeout_seconds=settings.executor_timeout_seconds,
    )
    LOGGER.info("Task finished.", extra={"task_id": str(record.task_id), "status": record.status})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

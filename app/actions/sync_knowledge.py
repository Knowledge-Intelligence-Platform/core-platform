from __future__ import annotations

import hashlib

from app.actions import ActionOutcome, OutcomeStatus
from app.knowledge_base import KnowledgeBase
from app.models import SyncJob
from app.tasks import PlanStep, TaskError, TaskRecord

TERMINAL_STATES: dict[str, OutcomeStatus] = {
    "COMPLETE": "complete",
    "FAILED": "failed",
    "STOPPED": "stopped",
}
EFFECT = "Start ingestion of published content from the configured knowledge source."


class SyncKnowledgeSource:
    task_type = "sync_knowledge_source"
    requires_approval = True

    def __init__(self, *, knowledge_base: KnowledgeBase, region: str) -> None:
        self.knowledge_base = knowledge_base
        self.region = region

    def scope(self) -> dict[str, str]:
        return {
            "region": self.region,
            "knowledge_base_id": self.knowledge_base.knowledge_base_id,
            "data_source_id": self.knowledge_base.data_source_id,
        }

    def plan(self) -> tuple[PlanStep, ...]:
        return (
            PlanStep(
                action="start_ingestion",
                target=self.knowledge_base.data_source_id,
                effect=EFFECT,
            ),
        )

    def start(self, record: TaskRecord) -> ActionOutcome:
        token = hashlib.sha256(
            f"{record.requester}:{record.scope['region']}:{record.scope['knowledge_base_id']}:"
            f"{record.scope['data_source_id']}:{record.task_id}".encode()
        ).hexdigest()
        return _outcome(self.knowledge_base.run(client_token=token))

    def poll(self, record: TaskRecord) -> ActionOutcome:
        job_id = (record.result or {}).get("ingestion_job_id")
        if job_id is None:
            raise TaskError("Task has no recorded ingestion job.")
        return _outcome(self.knowledge_base.sync_status(job_id))


def _outcome(job: SyncJob) -> ActionOutcome:
    status = TERMINAL_STATES.get(job.status, "running")
    return ActionOutcome(
        status=status,
        result={"ingestion_job_id": job.ingestion_job_id, "status": job.status},
    )

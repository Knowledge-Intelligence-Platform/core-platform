from __future__ import annotations

from dataclasses import dataclass

from app.tasks import TaskError, TaskRecord


@dataclass(frozen=True)
class TaskPolicy:
    approvers: frozenset[str]

    def can_view(self, identity: str, record: TaskRecord) -> bool:
        return identity == record.requester or identity in self.approvers

    def check_decision(self, approver: str, record: TaskRecord) -> None:
        if approver not in self.approvers:
            raise TaskError("This identity cannot decide knowledge tasks.", 403)
        if approver == record.requester:
            raise TaskError("A requester cannot decide their own task.", 403)

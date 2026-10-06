from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from app.tasks import PlanStep, TaskRecord


OutcomeStatus = Literal["running", "complete", "failed", "stopped"]


@dataclass(frozen=True)
class ActionOutcome:
    status: OutcomeStatus
    result: dict[str, str]


class ActionHandler(Protocol):
    """One task type: what it targets, what it plans and how it runs.

    `start` must be safe to repeat for the same record, because the service calls it
    again after an uncertain first attempt. Handlers receive only the persisted record.
    """

    task_type: str
    requires_approval: bool

    def scope(self) -> dict[str, str]: ...

    def plan(self) -> tuple[PlanStep, ...]: ...

    def start(self, record: TaskRecord) -> ActionOutcome: ...

    def poll(self, record: TaskRecord) -> ActionOutcome: ...

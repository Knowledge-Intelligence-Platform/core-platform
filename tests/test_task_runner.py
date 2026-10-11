import json
from typing import Any, cast
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from app.actions.sync_knowledge import SyncKnowledgeSource
from app.audit import AuditLog
from app.config import Settings
from app.policy import TaskPolicy
from app.runners import StepFunctionsRunner
from app.tasks import TaskError, TaskOrigin, TaskRunner, TaskService, TaskStore
from scripts.run_task import run
from tests.test_api import MemoryS3, TaskKnowledgeBase

SYNC = SyncKnowledgeSource.task_type
REQUESTER = TaskOrigin(kind="user", identity="reader@example.com")
ARN = "arn:aws:states:us-east-1:111111111111:stateMachine:kip-tasks"


class FakeStepFunctions:
    def __init__(self) -> None:
        self.started: list[dict[str, str]] = []
        self.error: str | None = None

    def start_execution(self, **kwargs: str) -> dict[str, str]:
        if self.error is not None:
            code, self.error = self.error, None
            raise ClientError({"Error": {"Code": code}}, "StartExecution")
        self.started.append(kwargs)
        return {"executionArn": f"{ARN}:{kwargs['name']}"}


def service(runner: TaskRunner) -> tuple[TaskService, TaskKnowledgeBase]:
    backend = TaskKnowledgeBase()
    return (
        TaskService(
            handlers=[SyncKnowledgeSource(knowledge_base=cast(Any, backend), region="us-east-1")],
            store=TaskStore(
                bucket="b", prefix="tasks", region="us-east-1", client=cast(Any, MemoryS3())
            ),
            audit=AuditLog(
                bucket="b", prefix="audit", region="us-east-1", client=cast(Any, MemoryS3())
            ),
            policy=TaskPolicy(approvers=frozenset({"approver@example.com"})),
            runner=runner,
        ),
        backend,
    )


@pytest.fixture
def workflow() -> tuple[TaskService, TaskKnowledgeBase, FakeStepFunctions]:
    client = FakeStepFunctions()
    tasks, backend = service(
        StepFunctionsRunner(state_machine_arn=ARN, region="us-east-1", client=client)
    )
    return tasks, backend, client


def test_approval_hands_the_task_to_the_workflow(workflow) -> None:
    tasks, backend, client = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    assert client.started == []
    tasks.decide("approver@example.com", task_id, "approve")
    assert client.started == [
        {
            "stateMachineArn": ARN,
            "name": f"task-{task_id}",
            "input": json.dumps({"task_id": str(task_id)}),
        }
    ]
    assert backend.tokens == []


def test_the_app_never_runs_the_task_in_workflow_mode(workflow) -> None:
    tasks, backend, _ = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    assert tasks.resume("reader@example.com", task_id).status == "approved"
    assert backend.tokens == []


def test_repeated_approval_resubmits_the_same_execution(workflow) -> None:
    tasks, _, client = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    client.error = "ServiceUnavailable"
    with pytest.raises(TaskError, match="workflow"):
        tasks.decide("approver@example.com", task_id, "approve")
    assert tasks.get("reader@example.com", task_id).status == "approved"
    tasks.decide("approver@example.com", task_id, "approve")
    client.error = "ExecutionAlreadyExists"
    tasks.decide("approver@example.com", task_id, "approve")
    assert [start["name"] for start in client.started] == [f"task-{task_id}"]


def test_rejected_tasks_are_never_submitted(workflow) -> None:
    tasks, _, client = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    tasks.decide("approver@example.com", task_id, "reject")
    assert client.started == []


def test_executor_runs_an_approved_task_to_completion(workflow) -> None:
    tasks, backend, _ = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    backend.job_status = "IN_PROGRESS"
    sleeps: list[float] = []

    def wait(seconds: float) -> None:
        sleeps.append(seconds)
        backend.job_status = "COMPLETE"

    record = run(tasks, task_id, poll_seconds=15, timeout_seconds=600, sleep=wait)
    assert record.status == "complete"
    assert sleeps == [15]
    assert len(backend.tokens) == 1
    assert record.result is not None and record.result["status"] == "COMPLETE"


def test_executor_refuses_unapproved_tasks(workflow) -> None:
    tasks, backend, _ = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    with pytest.raises(TaskError, match="approval"):
        run(tasks, task_id, poll_seconds=1, timeout_seconds=60)
    assert backend.tokens == []


def test_executor_times_out_instead_of_running_forever(workflow) -> None:
    tasks, backend, _ = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    backend.job_status = "IN_PROGRESS"
    ticks = iter([0.0, 100.0])
    with pytest.raises(TimeoutError):
        run(
            tasks,
            task_id,
            poll_seconds=1,
            timeout_seconds=60,
            sleep=lambda _: None,
            clock=lambda: next(ticks),
        )
    assert tasks.store.load(task_id)[0].status == "running"


def test_executor_events_are_attributed_to_the_executor(workflow) -> None:
    tasks, _, _ = workflow
    task_id = uuid4()
    tasks.propose(SYNC, REQUESTER, task_id)
    tasks.decide("approver@example.com", task_id, "approve")
    run(tasks, task_id, poll_seconds=1, timeout_seconds=60, sleep=lambda _: None)
    objects = cast(MemoryS3, tasks.audit.client).objects
    starting = json.loads(objects[f"audit/{task_id}/starting.json"][0])
    assert starting["actor"] == "executor"


def test_step_functions_runner_requires_a_state_machine() -> None:
    with pytest.raises(ValueError, match="STATE_MACHINE"):
        Settings(
            _env_file=None,
            knowledge_base_id="ABCDEFGHIJ",
            knowledge_base_data_source_id="KLMNOPQRST",
            s3_bucket="b",
            tasks_enabled=True,
            query_tokens={"reader@example.com": "reader-token", "a@example.com": "a-token"},
            task_allowed_identities={"reader@example.com"},
            task_approver_identities={"a@example.com"},
            task_runner="step_functions",
        )

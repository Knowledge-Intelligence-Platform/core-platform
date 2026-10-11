from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.tasks import TaskError, TaskRecord


class StepFunctionsRunner:
    """Hands an approved task to the Step Functions workflow that runs the executor.

    The execution name is derived from the task ID and the input is fixed, so a repeated
    submit for the same task returns the existing execution instead of starting another.
    """

    runs_in_app = False

    def __init__(self, *, state_machine_arn: str, region: str, client: Any = None) -> None:
        self.state_machine_arn = state_machine_arn
        self.client = client or boto3.client(
            "stepfunctions",
            region_name=region,
            config=Config(connect_timeout=5, read_timeout=15, retries={"mode": "standard"}),
        )

    def submit(self, record: TaskRecord) -> None:
        try:
            self.client.start_execution(
                stateMachineArn=self.state_machine_arn,
                name=f"task-{record.task_id}",
                input=json.dumps({"task_id": str(record.task_id)}),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ExecutionAlreadyExists":
                return
            raise TaskError(
                "The task workflow could not be started. Retry the decision.", 503
            ) from None
        except BotoCoreError:
            raise TaskError(
                "The task workflow could not be started. Retry the decision.", 503
            ) from None

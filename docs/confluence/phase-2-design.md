# KIP Phase 2 Design: Controlled Task Intelligence

## Purpose

This page describes how the Phase 2 roadmap is built. It records what exists and what each slice adds.

## Principles

- Agents read, reason and plan. They never hold credentials that can change anything.
- Deterministic executors with their own IAM roles perform approved steps only.
- Approved Confluence content is evidence for plans. It never creates a plan step.
- A task starts from an explicit task type and a configured trigger, never from a model reading a knowledge question.
- The trigger does not carry authority. Configuration fixes the task type, scope and approvers.

## Task lifecycle

1. A trigger creates a task with a fixed type and scope.
2. Read-only collectors gather live facts and the evidence service retrieves the governing standard.
3. An agent explains the findings and proposes steps from the task type's allowed actions, each citing its standard and page version.
4. Policy decides whether the plan needs approval. Reviewed rules decide, not the model.
5. An approver who is not the requester approves or rejects.
6. An executor runs the approved steps under a separate role.
7. Verification and the audit record complete the task.

Triggers can be a user request, a schedule, an AWS event or a GitHub event. Events are deduplicated by event ID, rate limited, and notify approvers because no user is waiting.

## Components

| Component | Responsibility | Status |
| --- | --- | --- |
| Evidence service (`app/evidence.py`) | Passages with source, space, last updated time and content hash | Built (2A-1) |
| Task service and records (`app/tasks.py`) | Lifecycle, origin, immutable scope, plan, result, resume | Built (2A-1) |
| Action handlers (`app/actions/`) | One module per task type | Sync handler built (2A-1) |
| Policy (`app/policy.py`) | Approver rules, approval requirement | Built (2A-1) |
| Audit log (`app/audit.py`) | Create-only event per task and step | Built (2A-1) |
| Workflow engine (`app/runners.py`, `infra/workflow.tf`) | Step Functions runs approved tasks with retries | Built (2A-2) |
| Executor (`scripts/run_task.py`) | ECS task with its own IAM role runs approved steps | Built (2A-2) |
| AWS review | Read-only checks and plans | Planned (2B) |
| GitHub relationships | Repository graph and pull request impact | Planned (2C, 2D) |

## Workflow decisions (2A-2)

- Approval stays in the application, protected by conditional writes and expiry. Step Functions starts only after approval, so the workflow never holds approval state or callback tokens.
- The executor is an ECS Fargate task from the same container image, not a Lambda function. It reuses the application code without separate packaging, runs only while a task executes, and has no idle cost.
- Each execution is named after its task, so repeated submissions cannot start duplicate work.
- `local` remains the runner for development; deployed environments use `step_functions`.

## Standards and rules

A rule is code with an ID. It records the standard it implements: a document ID and the `last_updated_at` it was reviewed against. When a plan retrieves that document and its `last_updated_at` is newer, the plan is flagged as "standard changed since this rule was reviewed" and needs a human to re-review the rule. A page edit cannot silently change what is enforced.

## Known limits

- Bedrock returns `_last_updated_at` for Confluence content but no version number, so the page version in plans and audit records is that timestamp plus a content hash.
- The audit prefix is create-only by application behaviour. Hardening with bucket-level controls such as S3 Object Lock belongs to the externally managed bucket.
- Retrieval is semantic, so rules pin their standard by document ID. Retrieval by query is only a fallback for explanation.

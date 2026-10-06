# KIP Knowledge-Source Tasks

## Purpose

KIP can help an operator refresh its approved knowledge after content is published.
For example: “I updated KIP's overview in Confluence. Prepare a knowledge sync.”

This is an opt-in capability. It is separate from the knowledge question-answering
flow and currently available through FastAPI and Swagger, not Slack.

## What KIP can do

- Inspect the configured source and its latest ingestion job.
- Prepare a sync proposal through an explicit operational request, showing the region, knowledge base, source and effect.
- Record an explicit approval or rejection from a configured approver who is not the requester.
- Start the approved sync and save the AWS ingestion job reference.
- Resume tracking across requests or application restarts.

KIP does not edit Confluence pages, change connector scope, read arbitrary AWS
resources or grant itself additional permissions. A completed ingestion job is not
proof that every expected page was indexed or that every answer is correct.

## Enable the workflow

Configure the existing region, KB ID, data-source ID and S3 bucket. Then configure:

| Setting | Meaning |
| --- | --- |
| KNOWLEDGE_INTELLIGENCE_TASKS_ENABLED | Set to true to expose task operations. Defaults to false. |
| KNOWLEDGE_INTELLIGENCE_TASK_ALLOWED_IDENTITIES | JSON list of requester identities already present in QUERY_TOKENS. |
| KNOWLEDGE_INTELLIGENCE_TASK_APPROVER_IDENTITIES | JSON list of approver identities already present in QUERY_TOKENS. Each requester needs at least one approver other than themselves. |
| KNOWLEDGE_INTELLIGENCE_TASK_PREFIX | Dedicated task-record prefix in the configured S3 bucket. Defaults to tasks. |
| KNOWLEDGE_INTELLIGENCE_AUDIT_PREFIX | Separate prefix for append-only audit events. Defaults to audit and must not overlap the task prefix. |

For example, allow `operator@example.com` only after assigning it a unique bearer
token in the server-controlled query-token mapping. Do not put tokens in this page.
Having permission to ask knowledge questions does not grant permission to run tasks.

For ECS deployments, set `tasks_enabled`, `task_allowed_identities`, `task_approver_identities` and `task_prefix`
through deployment inputs. Core Platform's existing Terraform root wires these
settings and grants the task role scoped source-inspection, ingestion and S3 access.
Review the full plan separately before deploying; enabling the feature in code does
not apply infrastructure.

The runtime needs GetDataSource, ListIngestionJobs, GetIngestionJob and
StartIngestionJob on the configured KB, plus GetObject, PutObject and prefix-scoped
ListBucket for task records. Customer-managed encryption keys may also require KMS
permissions. Keep the task prefix outside any indexed S3 knowledge-source prefix.
Restrict write access to task records because those records contain approval state.

## Try it through Swagger

Open `/docs` and use **Authorize** with the requester's bearer token. Choose the
**Knowledge tasks** endpoints.

1. Call `GET /tasks/source` to inspect the current source and latest job. This does
   not start a sync. An available source does not establish that its content is fresh.
2. Generate a new task UUID and call `POST /tasks/sync/{task_id}`.
3. Review the returned `task`: its exact target, effect, status and expiry.
4. Authorize with an approver's bearer token and call `POST /tasks/{task_id}/decision`
   with `{"decision":"approve"}` or `{"decision":"reject"}`. Approval records the
   decision and the approver but does not start ingestion.
5. After approval, the requester or an approver calls `POST /tasks/{task_id}/resume`
   to start the sync.
6. Call the same resume endpoint periodically to refresh AWS job status. A running
   response is not completion. Terminal results are complete, failed or stopped.

Generate a new UUID for each new task. Reuse it when retrying the same request.
The example UUID is illustrative, not a value to reuse for every sync.

`POST /tasks/sync/{task_id}` prepares the proposal directly. It does not invoke the
model, interpret a prompt or bypass approval. `GET /tasks/{task_id}` reads the
persisted record without polling AWS.

Every task record states its `task_type`, its `origin` (what started it and who or what
it was), an immutable `scope` (region, knowledge base and data source for a sync), the
`plan` it will carry out, and the `result` of execution. Each lifecycle step also writes a
create-only audit event under the audit prefix with the task and correlation IDs, the
actor and the status, never document content. If an audit event cannot be written, the
action does not proceed.

The task record and returned AWS status are authoritative. A conversational answer
is not approval and cannot start an action. Neither the task URL nor the decision
body can select a different AWS target or impersonate another user.

Knowledge prompts cannot create, approve or start sync tasks. A future scheduler,
event trigger, CLI or operator workflow can call these explicit endpoints without
changing the knowledge-answer contract.

## Approval and recovery

Only the requester and configured approvers can read or resume a task. Only an
approver can approve or reject it, and never a task they requested. A requester
must remain in the configured requester list to continue operating their task.
A task ID belongs to the requester who first used it; another requester receives
HTTP 409.

Proposals and unused approvals expire one hour after creation. Rejected tasks cannot
be approved later. An edited target requires a new task and a new approval.

Task state persists in S3. Conditional writes reject competing state changes with
HTTP 409; reload the record before retrying. Storage failures do not allow a new
start to proceed without a persisted starting record.

If AWS's start response is lost, retry resume using the same task ID. KIP reuses its
stable AWS client token to avoid duplicate starts. After ten minutes in an uncertain
starting state, KIP stops automatic retries and requires an operator to reconcile
the ingestion job in AWS. Do not create replacement tasks blindly during recovery.

Once AWS has accepted the ingestion job, it continues independently of the API
request. The workflow does not run a background poller or send completion notices;
resume refreshes its state on demand. The separate administrative sync endpoint and
operator CLI remain available under their existing permissions.

## Prompt caching

`KNOWLEDGE_INTELLIGENCE_BEDROCK_PROMPT_CACHING_ENABLED` defaults to false. When
enabled, KIP places an explicit cache checkpoint after stable system instructions.
Questions and retrieved passages remain outside that checkpoint; retrieval still
runs on every knowledge turn.

Amazon Nova Lite supports system-prompt caching but not tool-definition checkpoints.
Short prompts or infrequent requests may not produce useful cache hits. Check the
input, output, cache-read and cache-write token fields in knowledge invocation logs
before assuming cost or latency savings. Validate caching support again when changing
the configured model.

References: [AWS Nova Lite model capabilities](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html),
[Strands harness configuration](https://strandsagents.com/docs/user-guide/harness/reference/configuration/).

# KIP Phase 2 Roadmap: Controlled Task Intelligence

## Purpose

Knowledge Intelligence Platform currently provides grounded answers from approved organizational knowledge. Phase 2 extends KIP so it can help teams understand systems, prepare operational work and carry out approved actions in a controlled way.

The goal is not to give an AI agent unrestricted access to infrastructure or source-control systems. The goal is to create a governed task platform that can inspect approved systems, explain what it found, prepare a plan, request approval, execute only permitted actions and verify the result.

## Phase 2 vision

KIP will evolve from a knowledge assistant into a controlled intelligence and task platform:

```text
Understand request
        ↓
Retrieve approved knowledge and evidence
        ↓
Analyse systems and relationships
        ↓
Prepare an explicit plan
        ↓
Evaluate policy and request approval
        ↓
Execute permitted actions
        ↓
Verify the result and record evidence
```

Every task should have a clear owner, target scope, permission boundary, approval state, execution history and audit trail.

## Target architecture

KIP will contain three domain agents supported by a shared Core Platform control plane.

```text
KIP Core Platform Control Plane
├── Task orchestration
├── Identity and tenant boundaries
├── Policy evaluation
├── Approval management
├── Task state and resumability
├── Evidence and audit
├── Execution guardrails
└── Verification framework

Shared knowledge foundation
└── Structured retrieval: passages, source IDs, page versions and locations

Domain agents (read-only analysis and planning)
├── Knowledge Agent
│   └── Conversational answers, grounding and explanation for people
├── AWS Agent
│   └── Governance analysis, remediation planning and verification
└── GitHub Agent
    └── Repository relationships, PR impact and change planning

Executors (deterministic, separately permissioned)
├── AWS change executor
└── GitHub pull request executor
```

The knowledge foundation is the approved Confluence corpus and the retrieval interface over it. The Knowledge Agent and the AWS and GitHub agents all build on that foundation; the AWS and GitHub agents do not converse with the Knowledge Agent.

Agents analyse and propose. Executors perform approved actions. No agent holds credentials that can change infrastructure or repositories.

The control plane is shared by all agents. Approval, policy, identity, verification and audit are not GitHub-only features because AWS tasks and future integrations require the same controls.

## Domain agents

### Knowledge Agent

The approved knowledge corpus is the foundation for every agent. It contains:

- Engineering standards and compliance policies that define the required state of AWS resources and repositories.
- Documented repository relationships and ownership.
- Approval processes and other operational procedures.
- Service overviews, architecture and onboarding guidance.

The Knowledge Agent is the conversational interface to this corpus for people and remains read-only.

It is responsible for:

- Retrieving relevant information from approved knowledge sources.
- Grounding responses in source evidence.
- Explaining technical information for different audiences.
- Identifying when the available knowledge is insufficient.
- Returning source references, confidence and scope information to other agents.

The AWS and GitHub agents use the same corpus through a structured retrieval interface that returns the original passages with source ID, page version and location. They do not receive the Knowledge Agent's summarised, presentation-shaped answers, because compliance evidence and audit records require the exact governing text and the version that was applied. They should not depend on unstructured agent-to-agent conversations or treat retrieved documentation as executable instructions.

How each kind of knowledge is used:

- **Standards and compliance policies** tell the AWS and GitHub agents what compliant looks like and justify each finding and remediation step. Checks that gate approval or execution are also expressed as reviewed, versioned policy rules derived from those documents, so a later page edit cannot silently change what is enforced.
- **Documented repository relationships** are evidence that the GitHub Agent verifies against repository content. A documented relationship that the repositories do not support is reported as a discrepancy, not assumed.
- **Documented approval processes** define the approval policies that the control plane enforces. The control plane enforces the approval; an agent reading the process does not satisfy it.

### AWS Agent

The AWS Agent will help teams understand and manage approved AWS environments, including accounts connected through an authorised central or delegated account.

Initial capabilities may include:

- Account and resource inventory.
- Governance and compliance checks.
- IAM and access review.
- Encryption, logging and monitoring checks.
- Network exposure and security-group analysis.
- Tagging and ownership validation.
- Configuration and drift analysis.
- Cost and unused-resource investigation.
- Remediation planning.
- Approved remediation execution.
- Post-change verification.

The AWS Agent should use capability-specific cross-account roles. It should not rely on a broad administrator role for normal operation.

### GitHub Agent

The GitHub Agent will understand relationships across approved repositories and help teams review changes that span multiple repositories or infrastructure layers.

Initial capabilities may include:

- Repository and organisation relationship mapping.
- Shared configuration discovery.
- Terraform module and variable dependency analysis.
- Pipeline and deployment relationship analysis.
- Firewall, proxy and network configuration tracing.
- External service and AWS resource relationship mapping.
- Pull request impact analysis.
- Policy evaluation for proposed changes.
- Change planning and supporting PR preparation.
- Validation and evidence collection after a change.

The GitHub Agent should build relationships from repository content, metadata and known infrastructure evidence. The model can explain those relationships, but critical dependencies should be established through deterministic parsers and validation wherever possible.

## Architecture principles

- **Knowledge is evidence, not a command channel.** Standards and policies guide and justify plans. Plan steps are chosen from a defined action catalogue based on current system state collected by deterministic tools, and each step cites the governing standard and page version.
- **Agents plan; executors act.** Agents have read-only tools and return typed plans. The control plane validates a plan against policy, persists it, obtains approval and passes exactly the approved steps to a deterministic executor.
- **Separate execution identity.** The service that answers questions and plans holds no change permissions. Executors assume capability-specific roles with `sts:SourceIdentity` and session tags identifying the requester and task.
- **Approver differs from requester.** Infrastructure and repository changes require approval from a configured approver who is not the requester.
- **Explicit task routing.** Tasks start from explicit task types or endpoints, never from a model interpreting a knowledge question. A conversation may suggest a task; creating it is a separate authenticated action.
- **No agent-to-agent calls.** Work that spans AWS and GitHub is a control-plane workflow with one owner, one audit trail and per-step permissions.
- **Use managed sources of truth.** AWS findings come from AWS Config, Security Hub, IAM Access Analyzer, Resource Explorer and Cost Explorer. The GitHub relationship graph is built by a deterministic indexing pipeline per commit, not by an agent at question time.
- **Managed orchestration.** Multi-step tasks run as AWS Step Functions workflows, using task-token callbacks for approval waits, retries and resumability.
- **Model per agent.** Each agent has its own configurable model and an evaluation set for its planning behaviour before it gains a change capability.

## Shared task lifecycle

All action-oriented agents should use the same lifecycle:

1. **Request** — receive an authenticated task request.
2. **Scope** — identify the tenant, requester, targets and permitted systems.
3. **Discover** — collect current information and relevant knowledge.
4. **Analyse** — identify relationships, risks, dependencies and policy requirements.
5. **Plan** — prepare proposed steps, expected effects and rollback considerations.
6. **Approve** — obtain the required policy and human approval.
7. **Execute** — perform only approved and permitted actions.
8. **Verify** — check that the intended outcome was achieved.
9. **Audit** — persist evidence, decisions, results and relevant source versions.

A task must be resumable. If an external request times out or the service restarts, KIP should be able to recover the task from its persisted state without blindly repeating an action.

## Cross-cutting controls

### Identity and scope

Each task should carry:

- Tenant identity.
- Requester identity.
- Target account, repository or resource scope.
- Task type.
- Correlation and idempotency identifiers.
- Required capability permissions.

The agent must not infer authority from the wording of a request. Authority comes from configured identity, scope and policy.

### Permissions

Permissions should be separated by capability and lifecycle stage:

- Read knowledge.
- Read AWS resources.
- Read GitHub repositories.
- Prepare a plan.
- Create a GitHub branch or pull request.
- Approve a proposed action.
- Execute an AWS or repository change.
- Verify the outcome.

The permission to ask a knowledge question must not grant permission to perform an action.

### Policy and approval

The policy engine should determine whether a task is allowed, requires additional review or must be rejected. Human approval should be required for changes that affect infrastructure, access, repositories, production resources or other protected systems.

An agent should not approve its own change. The system should preserve the difference between:

- Policy evaluation.
- Agent recommendation.
- Human approval.
- Actual execution.

### Evidence and audit

KIP should record enough evidence to explain what happened:

- The original request.
- The authenticated requester.
- Knowledge and repository versions used.
- AWS accounts and resources inspected.
- The proposed plan.
- Policy results and approval decisions.
- Actions performed.
- Verification results.
- Errors, retries and recovery decisions.

Audit records should be protected from normal task mutation and linked by a correlation ID.

## Delivery roadmap

### Phase 2A: Task and control-plane foundation

**Status:** Phase 2A is built. 2A-1 added the evidence service, generic task records with origin and immutable scope, action handlers, policy and audit. 2A-2 added the Step Functions workflow and a separate executor task and role. See the Phase 2 design page.

Establish the reusable task model before adding broad execution capabilities.

Deliverables:

- Common task schema and lifecycle states.
- Task orchestration and resumability.
- Tenant and requester scope propagation.
- Capability and permission model.
- Approval and policy interfaces.
- Idempotency and retry handling.
- Evidence and audit record format.
- Standard plan and execution result contracts.
- Structured retrieval interface returning passages with source ID, page version and location.
- Action catalogue and typed plan schema with per-step standard citations.
- Approval policies with requester and approver separation, derived from documented approval processes.
- Step Functions workflow for the task lifecycle with approval callbacks.
- Separate executor identity and capability-specific roles.
- Per-agent model configuration and planning evaluation sets.

Success criteria:

- A task can be created, reviewed, approved, resumed and completed.
- An unauthorised task cannot access a protected capability.
- An interrupted task can recover without duplicating an external action.
- Every completed task has evidence and a verification result.
- A requester cannot approve their own infrastructure or repository change.
- Every plan step cites the standard and page version that justified it.

### Phase 2B: AWS Agent read-only governance

Start with visibility and analysis before enabling changes.

Deliverables:

- Central or delegated-account execution pattern.
- Approved member-account role assumption.
- Account and resource inventory.
- Initial governance checks.
- IAM, encryption, logging and network findings.
- Evidence-backed governance reports.
- Findings grouped by account, owner, severity and policy.

Success criteria:

- The AWS Agent can inspect only configured accounts and regions.
- Findings identify the affected resource and supporting evidence.
- The agent produces a remediation plan without applying changes.

### Phase 2C: GitHub relationship intelligence

Build a reliable relationship graph for approved repositories.

Deliverables:

- Approved organisation and repository allowlist.
- GitHub App or equivalent scoped integration.
- Repository metadata and commit snapshot collection.
- Relationship graph for repositories, modules, pipelines, accounts, networks and services.
- Deterministic parsers for supported configuration formats.
- Evidence links for each relationship.

Success criteria:

- KIP can explain why two repositories are considered related.
- Relationships point to specific files, configurations, commits or external evidence.
- Analysis is tied to a known commit or repository version.

### Phase 2D: Pull request impact analysis

Use the relationship graph to understand changes that cross repository boundaries.

Deliverables:

- Changed-file and changed-resource analysis.
- Affected repository and service detection.
- Configuration and network dependency analysis.
- Potential missing companion changes.
- Risk and blast-radius summary.
- Validation recommendations.
- Evidence-backed impact report on the pull request.

Success criteria:

- A reviewer can understand affected systems without manually searching every repository.
- The report identifies evidence and uncertainty separately.
- The analysis does not claim a dependency without a supporting relationship.

### Phase 2E: Governed change workflows

Introduce controlled actions after read-only analysis is trusted.

Deliverables:

- Policy-based approval requirements.
- Change-plan generation.
- GitHub branch and pull request preparation.
- AWS remediation execution for explicitly approved actions.
- Pre-change and post-change validation.
- Rollback or recovery guidance.
- Complete audit evidence.

Success criteria:

- No protected change executes without the required approval.
- Execution is limited to the approved target and action set.
- Verification can identify success, failure or an uncertain outcome.
- A reviewer can reconstruct the complete task timeline.

## Example Phase 2 workflows

### AWS governance review

```text
Request governance review
        ↓
Identify permitted AWS accounts
        ↓
Inspect resources and retrieve relevant policies
        ↓
Evaluate governance rules
        ↓
Produce findings and remediation plan
        ↓
Request approval for selected remediation
        ↓
Execute through a capability-specific role
        ↓
Verify and record evidence
```

### Cross-repository pull request review

```text
Receive pull request
        ↓
Analyse changed files and resources
        ↓
Traverse approved repository relationships
        ↓
Identify affected services, accounts and network paths
        ↓
Retrieve applicable documentation and policies
        ↓
Produce impact and validation report
        ↓
Prepare supporting changes only when approved
        ↓
Verify the resulting repository state
```

## Core Platform and tenant responsibilities

### Core Platform

- Agent interfaces and orchestration.
- Task lifecycle and resumability.
- Policy, approval and audit contracts.
- Identity and scope propagation.
- Connector interfaces and execution guardrails.
- Common evidence and verification formats.
- Observability, retries and failure handling.

### Tenant deployment

- Approved AWS accounts and regions.
- Cross-account role mappings.
- Approved GitHub organisations and repositories.
- Knowledge sources and source boundaries.
- Governance policies and severity rules.
- Allowed actions and approval requirements.
- Tenant-specific parsers or relationship mappings.
- Operators and reviewers.

The Core Platform must remain generic. Tenant-specific accounts, repositories, policies, source identifiers and credentials belong in deployment configuration or the tenant repository.

## Explicit non-goals for the first release

- Unrestricted administrator access.
- Automatic approval of agent-generated changes.
- Access to unapproved AWS accounts or repositories.
- Treating documentation as executable instructions.
- Relying only on model reasoning to infer critical infrastructure relationships.
- Applying changes without a persisted plan and approval record.
- Replacing existing source-control review or AWS governance processes.

## Phase 2 decision record

The following decisions define the direction of Phase 2:

- KIP will use three domain agents: Knowledge, AWS and GitHub.
- The Knowledge Agent is a shared, read-only foundation capability.
- AWS and GitHub agents will use structured knowledge retrieval rather than free-form agent-to-agent delegation.
- Policy, approval, verification, audit and task orchestration are shared Core Platform responsibilities.
- Domain agents will use isolated, capability-specific tools and permissions.
- Read-only analysis will be delivered before governed execution.
- All task execution will be tenant-scoped, approval-aware, resumable and auditable.
- The approved knowledge corpus, including standards, compliance policies, repository relationships and approval processes, is the shared foundation. Agents consume it through structured retrieval, not through the Knowledge Agent's conversational answers.
- Agents plan with read-only tools; deterministic executors with separate identities perform approved actions.
- Enforced checks are reviewed policy rules derived from the documented standards.
- Requesters cannot approve their own changes.
- Tasks are started explicitly, never by model routing of a knowledge question.
- Cross-domain work is orchestrated by the control plane using AWS Step Functions; agents do not call each other.

## How this roadmap should be used

This page records the agreed direction for KIP Phase 2. It is a product and architecture roadmap, not a commitment that every capability is already implemented.

Each future implementation should identify the relevant roadmap phase, update the capability status, document its permission boundary and include a verification strategy before being considered complete.

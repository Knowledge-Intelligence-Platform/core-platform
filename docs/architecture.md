# Core Platform architecture

## Current runtime

One deployment serves one configured Bedrock knowledge base. FastAPI authenticates
bearer tokens against server-controlled account mappings. Signed Slack events resolve
the sender's email locally, and replies are delivered in direct messages. Local
identities separate conversation history and optional persisted sessions.

Bedrock retrieval receives the question, KB ID and result limit. No userContext or
directory identity is sent. The Confluence connector must have ACLs and identity
crawling disabled. Every authorized application user can access the deployment's
approved knowledge, so select source spaces accordingly.

The managed KB handles Confluence crawling, parsing, embeddings and storage.
Its managedSearchConfiguration returns passages for a single Strands BedrockModel
agent using Amazon Nova Lite. Empty retrieval refuses before generation; service
errors remain errors. The REST contract returns answer text and removes internal
source markers. Slack retains text flows, knowledge maps, follow-ups and streaming.

## Infrastructure and operations

The knowledge agent uses `strands_harness.create_harness` with explicit
Nova model instances. Built-in tools, environment injection, local persistence,
long-term memory and background execution are disabled. Knowledge presentation
skills, conversation management and optional S3 sessions remain explicit.

An independent opt-in task API supports source inspection and explicit sync proposals.
Task operators are a configured subset of API identities; records are isolated
by identity in S3. Only the owner can approve or resume a task. Conditional writes
protect state transitions across application instances. A sync starts only after
approval and a durable starting record; retries reuse a target-bound client token.
Polling returns the AWS ingestion state without assuming retrieval is successful.
This task path bypasses knowledge retrieval and model prompts, not authentication
or authorization.

Optional prompt caching adds a checkpoint after stable system instructions. It
does not cache answers, skip retrieval, or add unsupported Nova tool checkpoints.
Existing invocation metrics include input, output, cache-read and cache-write tokens.

Terraform defines the KB, connector and application in the same infra root and state.
The existing KB execution role and connector secret remain external references.
ECS receives the region, KB IDs and Amazon model selection. API and Slack credentials
are injected from the application secret. No OpenAI key is required.

The administrative sync endpoint returns an ingestion job ID with HTTP 202.
Readiness checks KB availability. S3 supports optional feedback and persisted
conversations. Authentication is still an application responsibility.

Old application-side parsing, registry loading, embeddings, hybrid search and vector
storage modules have been removed, together with their Terraform definitions for the
S3 Vectors bucket and index, component registry, AppConfig and their IAM roles and
policies. A redesigned registry is future work.

## Preserved visual documentation

![Previous custom-index architecture](architecture.svg)

The [PNG export](architecture.png) and graphics in visuals/ are
preserved historical assets. They describe the previous custom-index design.
The runtime description above supersedes their OpenAI, custom embedding and
S3 Vectors connections.

## Boundaries

There is no shared tenant router, SSO integration or separate technical/nontechnical
profile service. Bearer mappings are the current authentication mechanism.
With connector ACLs disabled, Confluence page permissions are not enforced per user
by this application. Tenant/source approval must reflect the intended audience.

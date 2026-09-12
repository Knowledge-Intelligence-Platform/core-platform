# Core Platform architecture

![Implemented architecture](architecture.svg)

This is the canonical architecture diagram for the current code. The PNG export
is [available here](architecture.png). Older presentation graphics in `visuals/`
are retained assets, not the current architecture specification.

## Knowledge preparation

`app/main.py:build_application()` composes the registry, ingestion, storage,
retrieval, agent and optional Slack integration. There is one configured knowledge
context per application instance; there is no shared-service tenant router.

`app/ingestion.py` reads Confluence PDF exports from the configured S3 prefix,
optional mapped GitHub README files and registry-generated documents. PDF and
Markdown parsing produce `ParsedDocument`; registry data is converted directly
to that model. Optional visual analysis adds page-grounded descriptions.
Chunking and OpenAI embeddings feed `app/vector_store.py`, which persists vectors
in S3 Vectors and complete chunks in ordinary S3. Partial ingestion retains chunks
from unselected sources. The keyword index is rebuilt after ingestion and restored
from persisted chunks at application startup.

## Answering

`app/agent.py:_prepare()` performs retrieval before generation on every knowledge
turn, incorporating the preceding question when needed. `app/search.py` combines
semantic search with an in-memory TF-IDF index through reciprocal rank fusion and
limits dominance by a single document. Retrieved passages carry source IDs.

A single Strands agent uses `OpenAIResponsesModel` with structured output and
instruction-only presentation skills. The answer contract normalizes refusals and
cleans diagrams and follow-ups. These checks enforce presentation rules; they are
not an independent factual-verification model.

The REST endpoint returns answer text with internal source markers removed. Slack
supports mentions, direct messages and thread replies, optional progressive
delivery, grounded diagrams and feedback. Coverage questions on the Slack path
are handled deterministically before the agent. Slash commands are not supported.

## Supporting services and deployment

Registry resolution tries configured AppConfig, current S3 and previous S3 versions,
then a last-known-good cache. With no remote sources configured, it reads an external
local directory. This is configuration loading, separate from semantic retrieval.
Contacts are excluded from indexed registry text and attached structurally at delivery.

Conversation context is bounded in process; S3 session persistence and summarization
are optional. Diagrams and feedback use S3. Terraform defines API Gateway forwarding
to a public ALB and ECS Fargate, with ECR images, Secrets Manager and CloudWatch.
These are code-defined relationships, not a verification of deployed resources.

## Planned work

Amazon Bedrock, direct Confluence space connections and richer audience adaptation
are stated product directions. The current code explicitly uses OpenAI for generation,
embeddings and optional page vision. Presentation skills already provide some
question-specific formatting; a technical/nontechnical user profile is not represented
as a separate implemented service. The diagram does not imply these future features
are already available.

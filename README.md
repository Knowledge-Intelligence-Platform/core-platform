# Knowledge Intelligence Platform

A source-grounded knowledge agent for KIP. Ask it a question in Slack and it answers from
approved KIP documentation - or tells you plainly that it cannot.

![Architecture](docs/architecture.svg)

## What it does

It answers questions about KIP services, onboarding, prerequisites, validation and
runbooks, using three approved sources and nothing else:

| Source | What it contributes |
| --- | --- |
| Confluence PDF exports in S3 | the bulk of KIP documentation, including descriptions of the diagrams on each page |
| `README.md` from mapped repositories | how a component is actually used |
| The component registry | who owns what, how components relate, and knowledge agreed outside Confluence |

Every answer is built from passages retrieved for that question. When the retrieved
passages do not cover what was asked, the answer is exactly this and nothing else:

> I don't have enough information to answer that reliably.

That refusal is enforced in code, not merely requested of the model. So is everything
around it: source markers are stripped before an answer reaches you, a diagram cannot
accompany a refusal, and a component's contact details never enter the search index.

**It is not a developer assistant.** It will not analyse source code, Terraform, pipeline
internals, variable usage or IAM policy, and it will not describe live infrastructure
state. Ask it what the platform *documents*, not what the platform is *currently doing*.

---

# User guide

## Asking a question in Slack

Two ways, both plain English - there are no commands to learn:

- **Mention the app** in a channel: `@KIP Knowledge Hub how does operations management work?`
- **Send it a direct message** - the same, without a channel
- **Reply in a thread** - the app keeps the conversation, so follow-ups can say "and for
  Windows?" without repeating the subject

The answer streams in as it is written. Underneath it you may get:

- **A diagram** - a flow when the answer describes an ordered process, or a radial
  knowledge map when it breaks a subject into areas. Both are drawn only from what the
  answer actually says.
- **Follow-up buttons** - questions the retrieved content can genuinely answer. Click one
  and it asks it for you.
- **Feedback buttons** - Helpful / Partly / Not helpful. These record only a random answer
  id, the response type, the rating and a timestamp. Never your name, your channel, your
  question or the answer.

## Asking good questions

The agent answers from documentation, so questions that name a subject work best:

| Instead of | Ask |
| --- | --- |
| "How do I get a cluster?" | "How do I onboard to KIP Service as a Service?" |
| "What about patching?" | "How does centralised operations management work?" |
| "Who do I talk to?" | "Who owns OS Builds?" |

Follow-ups inside a thread can be short - the conversation supplies the subject.

## Finding out what it knows

Ask it what it knows:

```text
@KIP Knowledge Hub what do you know?
```

It reports how many passages it holds, which components have Confluence documentation, a
README, both or nothing, and how many indexed documents no component claims. This is
computed from the index directly rather than answered by the agent, because it is knowledge
about the system rather than about KIP.

Use it when an answer surprises you. "No documentation" against a component explains a
refusal far better than the refusal itself does.

## When it refuses

A refusal means the approved sources do not cover the question. Usually one of:

- **the documentation does not exist** - the honest answer is that nobody has written it
- **it exists but was never exported** - Confluence pages reach the platform as PDF exports
  under the approved S3 prefix; a page nobody exported is invisible to it
- **the question is out of scope** - code, Terraform, pipelines, IAM, live state

It will not guess to fill the gap, which is the point. If a refusal is wrong, the fix is
usually to export the missing page or record the knowledge as a registry note.

## Using the API

```bash
curl -X POST https://<host>/knowledge/query \
  -H 'content-type: application/json' \
  -d '{"prompt": "How does centralised operations management work?"}'
```

```json
{ "answer": "Centralised Patch Management is the KIP capability that ..." }
```

The response contains the answer text and nothing else. Internal source identifiers are
never returned, and the API does not produce diagrams. Pass `conversation_id` to continue a
conversation across calls.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | liveness |
| `GET /ready` | readiness, including how many passages are cached |
| `POST /knowledge/query` | ask a question |
| `POST /slack/events` | Slack events, interactivity and the slash command |
| `GET /diagrams/{id}.png` | serves a rendered diagram to Slack |
| `POST /admin/reindex` | rebuild the index; requires `X-Admin-Token` |

## Adding knowledge

**A Confluence page** - export it as a PDF into the approved S3 prefix, then re-run
ingestion. Anything under that prefix is approved by the act of being put there.

**A repository README** - map the repository to a component in the registry.

**Something that never reached Confluence** - a decision from a call, a convention nobody
wrote down - record it as a note against the component in the registry:

```yaml
notes:
  - note: >-
      Windows images follow the same golden-image process as RHEL. The Windows base AMI
      choice is still open, so treat base-image specifics as RHEL-only.
    recorded: 2026-08-22
    source: KIP platform discussion
```

Note text is indexed and can be used to answer questions; `recorded` and `source` are not
indexed and exist so notes can be audited and expired. State the exception in the same note
as the rule - asserting that one thing follows another's process lets the platform repeat
*every* detail of that process, including the parts that do not transfer.

---

# Running it yourself

## Setup

Python 3.14 is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
cp .env.example .env
```

Populate `.env`, then run the API:

```bash
fastapi dev app/main.py
```

Diagram rendering uses Graphviz. Without the `dot` binary the platform falls back to a
plainer renderer rather than failing:

```bash
brew install graphviz
```

## Indexing

```bash
python scripts/ingest.py
```

Confluence parsing and visual analysis dominate the cost of a run, so rebuild only what
changed:

```bash
python scripts/ingest.py --source registry
python scripts/ingest.py --source github --source registry
```

Sources you do not select keep their existing content - a subset run never prunes the rest.

If the vector index is lost but the chunk store survives, do not re-ingest. Re-embedding
the stored chunks costs embedding calls only:

```bash
python scripts/rebuild_vectors.py
```

## Checking a change

```bash
python scripts/validate_search.py "How do I onboard to KIP Service as a Service?"
```

Prints the answer the agent would give, plus the structured fields behind it - useful for
seeing whether a question produces a flow, a map, or a refusal before trying it in Slack.

```bash
python scripts/evaluate.py
python scripts/evaluate.py --judge
```

Scores the agent against `evals/datasets/*.yaml` and writes a scorecard to
`evals/reports/`. The deterministic evaluators check refusal discipline, forbidden claims,
expected coverage and internal leakage. `--judge` adds LLM-as-judge faithfulness and
refusal evaluators, which make extra model calls.

## Tests and checks

Everything runs offline - no AWS, OpenAI or Slack calls:

```bash
pytest
ruff check .
mypy
```

## Deploying

```bash
./deploy.sh
```

Initialises the Terraform backend, creates ECR first, builds and pushes the image, applies
the rest, and waits for the service to stabilise. It needs `infra/backend.hcl` (copy
`infra/backend.hcl.example`) and `infra/terraform.tfvars`.

If the component registry has been published but never deployed, it also starts that first
AppConfig deployment before restarting the service, so the new task reads the published
registry rather than the copy bundled in the image. It never publishes the registry itself -
changes to the registry go through its own repository.

The image is built for `linux/amd64` because Fargate runs x86 - a native build on Apple
Silicon will not start.

`destroy_resources.sh` tears down the compute while preserving S3, S3 Vectors, Secrets
Manager, ECR and AppConfig, so teardown never costs you the embeddings, the parsed content,
or the registry's identifiers and deployment history.

## Configuration

All settings use the `KNOWLEDGE_INTELLIGENCE_` prefix. Required:

| Setting | Purpose |
| --- | --- |
| `S3_BUCKET` | bucket holding Confluence exports, chunks and diagrams |
| `OPENAI_API_KEY` | model access |
| `OPENAI_MODEL` | the answering model |
| `VECTOR_BUCKET_NAME` | S3 Vectors bucket |

Frequently changed:

| Setting | Default | Purpose |
| --- | --- | --- |
| `VECTOR_TOP_K` | `25` | candidates retrieved from each side before fusion |
| `AGENT_MAX_SEARCH_RESULTS` | `5` | passages passed to the model |
| `VISUAL_ANALYSIS_ENABLED` | `true` | describe diagrams on PDF pages during ingestion |
| `INGEST_UNMAPPED_DOCUMENTS` | `true` | index documents no component maps, without an owner |
| `SLACK_ENABLED` | `false` | enable Slack delivery |
| `GITHUB_ENABLED` | `false` | enable README ingestion |
| `SESSION_PERSISTENCE_ENABLED` | `false` | keep Slack threads across a restart |
| `REGISTRY_DOCUMENT_KEY` | – | read the published registry from S3 instead of the bundled copy |
| `REGISTRY_APPCONFIG_APPLICATION` | – | read the registry through AWS AppConfig |

In AWS, one Secrets Manager entry carries `OPENAI_API_KEY`, the Slack tokens, and
`GITHUB_TOKEN` and `ADMIN_TOKEN` where used. Terraform reads that secret; it does not
create it.

## Privacy

The platform is deliberately incurious about people. Feedback records no user, channel,
question or answer. Logs carry a correlation id, an operation and a duration - never
document text, embeddings or personal data. A component's `contact` details and a note's
provenance are held structurally and never reach the search index or the model prompt.

## Further reading

- `AGENTS.md` - the product specification: grounding, presentation and boundary rules
- `../CLAUDE.md` - how the code is built, and the invariants worth knowing before changing it

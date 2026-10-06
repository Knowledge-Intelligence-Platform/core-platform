# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

AGENTS.md (imported above) is the authoritative list of product, security and engineering
rules. This file adds commands and the architecture map.

## Commands

Python 3.14 in the existing `kip` conda env, which already has all dependencies. Don't create
another venv or reinstall. Non-interactive shells start on base Anaconda (`/opt/anaconda3/bin/python`,
which lacks `strands`), and `conda activate` fails there, so call tools through the env's
interpreter: `/opt/anaconda3/envs/kip/bin/python -m pytest` (likewise `-m mypy`, `-m ruff`).

```bash
pip install -r requirements.txt && pip install -e ".[dev]"   # runtime deps live only in requirements.txt
fastapi dev app/main.py                                      # local API; Swagger at http://127.0.0.1:8000/docs
pytest                                                       # all offline tests
pytest tests/test_api.py::test_name                          # single test
ruff check . && ruff format --check .
mypy                                                         # strict; covers app/ and scripts/
python -m compileall -q app scripts
python -m scripts.ingest                                     # start Bedrock KB sync (operator AWS creds)
python -m scripts.validate_search "question"                 # trusted local retrieval+answer
python -m scripts.evaluate --datasets /path/to/datasets      # optional; datasets live outside this repo
terraform -chdir=infra validate                              # only when infra/*.tf changes
docker build .                                               # check container buildability
```

`./build.sh` pushes the image to ECR and `./deploy.sh` runs Terraform. Both touch real
AWS: do not run them, `terraform apply`, or `destroy_resources.sh` unless asked.

## Architecture

Everything is composed explicitly in `app/main.py:build_application` from `Settings`
(`app/config.py`, pydantic-settings, env prefix `KNOWLEDGE_INTELLIGENCE_`, loaded from `.env`).
The resulting `Application` lives on `app.state` and is fetched per request; there is no DI
framework or global singletons beyond that.

Request path:

1. **Entry** – `POST /knowledge/query` resolves the caller's email from the bearer token via
   the server-side `QUERY_TOKENS` map; `POST /slack/events` verifies the Slack signature,
   resolves the sender's email, and hands work to `SlackIntegration` (`app/slack.py`) as a
   background task (DMs only; channels get a redirect).
2. **Retrieval** – `PlatformKnowledgeAgent` (`app/agent.py`) builds a retrieval query
   (short questions get expanded; the previous question is appended for follow-ups) and calls
   `KnowledgeBase.retrieve` (`app/knowledge_base.py`, Bedrock Agent Runtime). No results ⇒
   returns `INSUFFICIENT_ANSWER` without calling the model.
3. **Generation** – passages are injected as JSON data in the user turn; the system prompt is
   `app/instructions.md`. A per-identity Strands harness agent (`create_harness`, all built-in
   tools disabled, text-only presentation skills) returns structured `IntelligentResponse`.
   `_knowledge_answer` then enforces the output contract (refusals strip visuals/follow-ups,
   flow nodes vs. mind map, follow-up filtering) regardless of what the model produced.
4. **Delivery** – API returns `KnowledgeQueryResponse`; Slack renders blocks, optionally
   streams partial answers via `answer_stream`, shows a waiting message (`app/waiting.py`),
   and records anonymous feedback to S3 (`FeedbackStore`).

Conversations are keyed by local identity, held in memory with a window/summarizing manager,
and optionally persisted via `S3SessionManager` (failures fall back to in-memory).

Optional `/tasks` API (`app/tasks.py`): `KnowledgeTasks` + `TaskStore` persist sync proposals
in S3 with conditional writes; owner approval/resume is required before a Bedrock ingestion
job starts. `/admin/reindex` is a separate admin-token path that starts a sync and returns 202.

Infra (`infra/`) is one Terraform root with shared S3 state: VPC, ALB, ECS, ECR, the Bedrock
KB + Confluence data source (`bedrock.tf`), secrets and IAM. `s3vectors.tf`, `registry_*.tf`
and `appconfig.tf` own legacy resources that must be kept until a planned retirement.

## Testing

Tests are fully offline; `tests/conftest.py` provides shared fakes (`StubSearch`,
`StubStreamingAgent`, `make_chunk`, the `answer_payload` fixture) instead of AWS/Slack clients. New tests should reuse those fakes
rather than mocking boto3 directly. These are synthetic tests; they do not validate retrieval
quality against real Confluence content.

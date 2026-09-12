# Core Platform

Core Platform is the shared runtime for a source-grounded knowledge application.
It provides the application, retrieval pipeline, model integration, source adapters,
conversation delivery and infrastructure needed to run a knowledge assistant.

This repository contains reusable platform code. Tenant knowledge, source mappings,
deployment manifests, credentials and environment-specific settings belong in external
repositories.

## Capabilities

![Core Platform architecture](docs/architecture.svg)

See [architecture notes](docs/architecture.md) for implementation details and planned work.

- FastAPI knowledge query API
- Optional Slack delivery
- Document parsing, chunking, embeddings and hybrid search
- Amazon S3 and S3 Vectors storage
- Configurable model provider integration
- Registry loading through tenant-supplied configuration
- Grounded answers with citations and safe refusal behavior
- Optional streaming, conversation persistence, summaries and diagrams
- Terraform infrastructure templates and deployment scripts

## Repository layout

```text
app/       Application runtime and integrations
infra/     Terraform infrastructure
scripts/   Ingestion and operational commands
tests/     Offline tests and neutral fixtures
docs/      Core architecture documentation
```

## Local development

The project targets Python 3.14.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
cp .env.example .env
```

Run the API:

```bash
fastapi dev app/main.py
```

Run the checks:

```bash
pytest
ruff check .
mypy
python -m compileall -q app scripts
```

## Configuration

Runtime settings use the `KNOWLEDGE_INTELLIGENCE_` prefix. Configure storage,
model access, source adapters and delivery channels through environment variables.
Secrets must be supplied through the local environment or deployment secret manager
and must never be committed.

The platform accepts tenant-supplied registry data through the configured registry
directory or published document. The Core Platform repository contains neutral test
fixtures and does not define a customer or organizational knowledge domain.

## Extension boundary

An external tenant repository supplies knowledge definitions, source mappings and
tenant-specific content. An external deployment repository supplies environment and
infrastructure inputs. Core Platform remains responsible for runtime behavior,
interfaces and shared infrastructure templates.

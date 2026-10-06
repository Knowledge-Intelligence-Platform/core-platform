# KIP Phase 3 Roadmap: Reusable Platform Packaging

## Purpose

Core Platform application code is already tenant-neutral: the knowledge base, model, platform name and delivery channels are configured at deployment time. The infrastructure is not yet packaged the same way. Today the shared Terraform templates and the KIP reference deployment's inputs live in one Terraform root, so a team that adopts KIP has to clone the repository and modify it.

Phase 3 separates the reusable platform from any single deployment so that teams consume versioned releases instead of maintaining forks.

**Planned start:** end of December 2026.

## Problem

Cloning and modifying the repository creates long-lived forks:

- Every platform fix must be merged manually into each fork.
- Shared templates and deployment-specific inputs are hard to tell apart.
- Infrastructure variables kept for retired designs confuse new adopters.
- Deployment-specific values can leak into shared files, such as a hard-coded Terraform state bucket.

## Target structure

```text
core/                               Core Platform (versioned releases)
├── app/  scripts/  tests/
├── infra/modules/platform/         Reusable Terraform module
├── deployments/kip/                KIP reference deployment
│   ├── main.tf                     Calls the platform module
│   ├── terraform.tfvars.example
│   └── backend.hcl.example
└── docs/

team-deployment/                    Owned by an adopting team
├── main.tf                         module "platform" { source = "git::…//infra/modules/platform?ref=vX.Y.Z" }
├── terraform.tfvars                Team account, Region, KB, Confluence and Slack inputs
├── backend.hcl                     Team-owned Terraform state
└── .env                            Local runtime settings
```

An adopting team consumes two versioned artifacts:

- **Container image** — the application runtime, configured only through environment variables and secrets.
- **Terraform module** — the shared infrastructure, configured only through module inputs.

The team repository holds configuration and approved content decisions. It contains no copy of platform code.

## Prerequisites

Complete before Phase 3 starts:

- Keep the Terraform S3 backend block partial (`backend "s3" {}`), with bucket, key and Region supplied by each deployment's `backend.hcl`.
- Commit the current Bedrock Knowledge Bases runtime and infrastructure changes with passing validation.

## Delivery roadmap

### Phase 3A: Legacy infrastructure retirement

Remove infrastructure that belongs to the previous custom-index design before it becomes part of a published module interface.

Deliverables:

- Reviewed retirement plan for S3 Vectors, component registry, AppConfig and registry publishing resources.
- Reviewed `terraform plan` showing only the intended removals.
- Removal of the related variables, outputs and import steps.

Success criteria:

- No retained Terraform definition or variable refers to the removed custom-index pipeline.
- The KIP deployment plan is otherwise unchanged after retirement.

### Phase 3B: Platform module extraction

Move the shared infrastructure into a reusable module without recreating existing resources.

Deliverables:

- `infra/modules/platform` containing the shared resources.
- A documented module interface of required and optional inputs and outputs.
- `moved` blocks mapping every existing resource address to its module address.
- Updated deployment, import and destroy scripts.

Success criteria:

- The KIP deployment plan after extraction shows no resource replacements or deletions.
- The module contains no KIP-specific names, account IDs, ARNs or state locations.

### Phase 3C: Reference deployment and release

Make KIP an ordinary consumer of the platform it ships.

Deliverables:

- `deployments/kip` as the KIP reference deployment root using the platform module.
- Versioned releases that tag the container image and module together.
- A changelog that identifies breaking module input or runtime setting changes.

Success criteria:

- KIP deploys from a tagged release by the same path an adopting team would use.
- A platform upgrade is a version change in the deployment, not a merge.

### Phase 3D: Adopter template

Give adopting teams a minimal starting point.

Deliverables:

- A team deployment template with example inputs, backend configuration and environment settings.
- An adoption guide covering secrets, Bedrock model access, KB execution roles and the initial sync.
- Validation steps that a team runs before launch.

Success criteria:

- A new team can deploy in its own AWS account without changing Core Platform code.
- No KIP content, credentials or identifiers are required by the template.

## Decision record

- Core Platform is distributed as a versioned container image and Terraform module, not as a repository to fork.
- The KIP reference deployment consumes the same module as any adopting team.
- Deployment-specific values, including Terraform state locations, never appear in shared module code.
- Existing cloud resources are moved into the module with `moved` blocks rather than recreated.
- Legacy infrastructure is retired before the module interface is published.

Phase 3 changes the current engineering rule that keeps Terraform in a single existing infra root. That rule will be updated when Phase 3B starts.

## How this roadmap should be used

This page records the agreed direction for KIP Phase 3. It is not a commitment that any capability is already implemented. Each implementation should reference the relevant Phase 3 step and include a reviewed Terraform plan before any infrastructure change is applied.

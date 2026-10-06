# Platform Architecture

## Purpose

Knowledge Intelligence Platform is a reusable foundation for building organization-specific knowledge assistants. Teams use the shared platform code, deploy it in their own AWS environment and connect the documentation approved for their users.

KIP’s own deployment is an example of this model. It uses KIP documentation to validate the platform, but other teams can use the same foundation for their own applications, services and processes.

## Deployment model

Each adopting team has a separate application deployment and knowledge base. The deployment runs in the team’s AWS account and uses the team’s configuration, credentials, source connections and user access rules.

The platform code is shared, but knowledge and operational resources are not automatically shared between deployments.

| Area | Responsibility |
| --- | --- |
| Core Platform | Reusable application code, agent behavior and common interfaces |
| Deployment Config | Environment-specific infrastructure and deployment inputs |
| Tenant repository | Team-specific source mappings, knowledge definitions and supporting content |
| Team AWS account | Runtime resources, secrets, permissions and service costs |
| Connected knowledge sources | Approved documentation for that team’s assistant |

## Main components

- **User interfaces:** authenticated API access and optional signed Slack requests.
- **Application service:** receives requests, manages conversations and coordinates retrieval and response generation.
- **Knowledge retrieval:** Amazon Bedrock Knowledge Bases searches the connected approved content.
- **Agent:** a Strands-based agent uses retrieved passages to produce a grounded response.
- **Model:** Amazon Nova Lite is the current default. The model is configurable for deployments that use another compatible Bedrock model.
- **Optional persistence:** conversation sessions, summaries and feedback can be enabled according to deployment needs.

## Request flow

1. A user sends an authenticated question through an enabled interface.
2. The application identifies the local conversation and retrieves relevant passages from the deployment’s knowledge base.
3. The agent receives the question and retrieved passages as context.
4. The configured Bedrock model generates an answer grounded in that context.
5. The application returns the answer and any supported text-based flow or knowledge-map information.

If the knowledge base does not provide enough supporting information, the application returns its standard insufficient-information response instead of asking the model to guess.

## Knowledge boundary

Each deployment has one knowledge base containing the approved source content for that deployment. Authorized users of that deployment share access to that approved content.

The current setup does not pass Confluence user or group information to Bedrock retrieval and does not apply individual Confluence permissions to answers. Only connect content that is suitable for everyone authorized to use the deployment.

## Current and planned capabilities

The current platform supports grounded question answering, follow-up questions, streaming, text-based flows and knowledge maps. The current source integration uses Confluence through Amazon Bedrock Knowledge Bases.

Amazon S3 is an intended knowledge-source option, but its connector configuration and retrieval flow must be configured and validated for a deployment before being treated as ready for use.

An opt-in task API now supports live knowledge-source status, explicit sync proposals, approval and resumable ingestion tracking. It does not expose synchronization through knowledge prompts. Approval and execution remain authenticated application operations. Owner-bound task records persist in S3 with conditional updates and a stable AWS request token for start retries.

Knowledge and task requests have separate paths. Empty retrieval still refuses knowledge answers; a source-status request instead reads AWS directly. Knowledge access never grants task permission. The task workflow currently uses FastAPI and Swagger; Slack remains a knowledge interface. Broader integrations are future work.

System-prompt caching is optional and disabled by default. It preserves fresh retrieval on each knowledge turn and requires support from the selected model. The default remains Amazon Nova Lite, with model selection controlled by configuration.

The next major phase is documented in **KIP Phase 2 Roadmap: Controlled Task Intelligence**. It introduces a shared control plane and three domain agents: Knowledge, AWS and GitHub. Read-only analysis is planned before governed execution, with policy, approval, verification and audit shared across all agents.

Phase 3, planned from end of December 2026, is documented in **KIP Phase 3 Roadmap: Reusable Platform Packaging**. It separates the reusable Terraform module from the KIP reference deployment, so adopting teams consume versioned releases instead of maintaining forks.

## Design principles

- Keep the core platform independent of any team’s business domain.
- Keep deployment configuration and team knowledge outside the core code repository.
- Answer from approved retrieved content and identify when information is insufficient.
- Keep credentials and sensitive content out of prompts and logs.
- Treat retrieved documents as reference data, not executable instructions.
- Separate the permission to read knowledge from the permission to perform an action.

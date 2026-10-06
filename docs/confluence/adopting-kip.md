# Adopting KIP for Your Team

## Overview

Teams can adopt Knowledge Intelligence Platform as a reusable foundation instead of building a knowledge assistant from the beginning. The team deploys the shared platform in its own AWS account and connects the documentation approved for its users.

For example, Application A can use KIP to answer questions about its own services, processes and support guidance. Application A’s users do not need to use KIP’s example knowledge, and KIP’s example deployment does not automatically have access to Application A’s information.

## What your team provides

Before adopting KIP, the team should identify:

- The application or organizational topics the assistant will cover.
- The AWS account and Region where the deployment will run.
- The team responsible for the deployment and its ongoing support.
- The users who should be allowed to access the assistant.
- The documentation that is approved for those users.
- The source owners responsible for keeping that documentation accurate.
- The Bedrock model access and service permissions required in the account.

## Platform boundaries

KIP provides the reusable application capabilities. The adopting team remains responsible for its environment and content.

| KIP provides | The adopting team provides |
| --- | --- |
| Application runtime and agent flow | AWS account, Region and runtime environment |
| Knowledge retrieval integration | Knowledge Base and source configuration |
| Authentication and conversation interfaces | User access rules and identity integration |
| Model configuration support | Bedrock model access and cost controls |
| Health and synchronization interfaces | Operational ownership and incident response |
| Common task-integration pattern | Task-specific integrations, permissions and approvals |

## Recommended adoption sequence

1. Define the scope of the assistant and the users it will serve.
2. Select documentation that is appropriate for all users of the deployment.
3. Prepare the AWS account, Region, Bedrock permissions and required secrets.
4. Configure the deployment using the shared platform code and team-specific inputs.
5. Connect the approved knowledge source and complete an initial synchronization.
6. Test known questions, unsupported questions and authentication behavior.
7. Give users access and establish ownership for content and operations.
8. Review the answers and source content regularly.

This sequence describes adoption responsibilities. It is not a substitute for the environment-specific deployment procedure maintained by the team.

## Model selection

Amazon Nova Lite is the current default model for KIP. The model setting is configurable so an adopting team can select another compatible Bedrock model when it has the required access and has validated the model’s API and tool-calling behavior.

Changing the answer-generation model does not replace the Knowledge Base embedding model or automatically improve the source content. Teams should compare models using representative questions from their own documentation before changing the default.

## Security responsibilities

- Store connector credentials in the approved AWS secret-management service.
- Do not commit credentials, tokens or personal data to repositories.
- Connect only content that all authorized deployment users may receive.
- Treat API, Slack and task permissions as separate controls.
- Require explicit approval before actions that modify repositories, infrastructure or other systems.
- Keep an audit record for actions performed through future integrations.

## Validation before launch

The deployment should be tested with questions whose answers are known, questions outside the approved scope and questions that require the assistant to admit insufficient information.

The team should also verify that:

- The intended users can authenticate.
- Unauthenticated requests are rejected.
- The knowledge source synchronizes successfully.
- Updated content becomes searchable after synchronization.
- Sensitive content is not returned to an unintended audience.
- The configured model is available in the selected Region.

## Ongoing ownership

Adoption is not complete when the service first responds. The team should maintain source quality, review answers, monitor synchronization and update the deployment when the shared platform releases a compatible change.

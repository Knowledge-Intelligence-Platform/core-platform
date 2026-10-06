# KIP Overview

## About the platform

Knowledge Intelligence Platform, also known as KIP, is a reusable foundation platform that teams can adopt to build knowledge assistants for their own organization or application. Teams use the shared platform code, deploy it in their own AWS environment and connect their own approved knowledge sources.

The resulting assistant helps people find and understand information from that team’s documentation. Its subject matter comes from the connected knowledge, rather than being limited to information about KIP itself.

This page explains KIP’s capabilities, how it works and how to maintain the knowledge it relies on. For access guidance and example questions, read **Getting Started with KIP**.

## Why KIP exists

Many teams struggle to find the right information because it is spread across Confluence pages and other internal systems. Even when good documentation exists, people spend time searching through multiple pages, asking colleagues and trying to understand unfamiliar terminology.

KIP aims to make that information easier to access and understand. Instead of needing to know where an answer is documented, people can start with a question.

It also gives adopting teams a common foundation, so each team does not have to build and maintain its own question-answering application from scratch.

## One platform, separate team deployments

The intended adoption model is a separate deployment for each team or organization, using the same core code. It is not a single running application that automatically routes requests between multiple organizations.

For example, Application A deploys KIP in its own AWS account and connects its approved knowledge. Application B can deploy the same code in a different AWS account with different content. Each team is responsible for configuring its own infrastructure, credentials, knowledge base and user access. Sharing platform code does not mean sharing knowledge or credentials.

KIP’s own deployment is the first example of this model. It uses documentation about KIP to test the platform, while other deployments can answer questions about their own applications and processes.

## What is shared and what belongs to each team

- **Core Platform:** reusable application code and common capabilities, maintained independently of any team’s knowledge.
- **Deployment Config:** environment-specific deployment inputs for running the platform in the adopting team’s AWS account.
- **Tenant repository:** team-specific knowledge definitions, source mappings and supporting content. Here, a tenant means the team or organization adopting KIP.

The aim is to configure each deployment without adding organization-specific behavior to the core. Credentials belong in an approved secret manager or runtime environment, not in any of these repositories.

## Knowledge sources and current scope

The platform is intended to let teams connect their own Confluence spaces or Amazon S3 content through Amazon Bedrock Knowledge Bases.

The current integration and infrastructure configuration use a Confluence connector. An S3 knowledge-source configuration is not included in the current setup and needs to be configured and validated before being offered as a ready-to-use option. The intended source options should not be read as a claim that every connector has already been implemented and tested.

## Who KIP is for

- **Adopting teams** that want a reusable knowledge platform in their own AWS account.
- **New team members** who need an introduction to the platform and its terminology.
- **Application and delivery teams** looking for documented guidance and processes.
- **Operations and support teams** looking for procedures and troubleshooting information.
- **Non-technical readers** who need a simpler explanation of technical topics.

The usefulness of an answer depends on the documentation available. KIP cannot provide a reliable procedure or explanation that has not been documented in its connected knowledge sources.

## What KIP can help with

- Explain concepts described in the approved documentation.
- Summarize information spread across relevant pages.
- Help readers find and understand documented steps and prerequisites.
- Compare options when the documentation provides enough information.
- Present documented relationships as text-based flows or knowledge maps.
- Answer follow-up questions using relevant source information.

The knowledge assistant answers from documentation. A separate, opt-in task interface lets configured operators inspect the connected knowledge source and prepare, approve and track a sync. It does not provide general infrastructure access or unrestricted automation. Read **KIP Knowledge-Source Tasks** for the current workflow and controls.

## How KIP works

1. **Set up the team’s deployment.** Use the shared platform code with the team’s AWS environment and deployment configuration.
2. **Connect approved content.** The team’s selected knowledge sources provide the information its assistant can use.
3. **Sync the knowledge.** Amazon Bedrock Knowledge Bases processes the connected content and makes it searchable.
4. **Ask a question.** KIP retrieves relevant passages from that deployment’s knowledge base.
5. **Receive a grounded answer.** An Amazon AI model uses those passages to help answer the question.

The current setup uses Amazon Nova Lite through Amazon Bedrock. Each application deployment connects to one knowledge base, and authorized users of that deployment share its approved knowledge. Teams must verify model access and resource permissions in their own AWS accounts; access in KIP’s example account does not grant access elsewhere.

## Understanding the answers

KIP is designed to answer from approved documentation rather than fill gaps with guesses. If it cannot find enough supporting information, it will say that it does not have enough information to answer reliably.

This can happen when:

- The topic has not been documented.
- The relevant page is outside the connected source scope.
- New or updated content has not been synced yet.
- The available documentation does not contain enough detail.

AI-generated answers can still be incomplete or incorrect. Check the original documentation before taking actions that affect services, security or other people.

## Keeping this space useful

This Confluence space documents the shared KIP platform. Adopting teams maintain their application-specific documentation in their own selected sources. They do not need to replace this space with their own content or include KIP documentation in every deployment’s knowledge base.

Write pages so they can help both people browsing Confluence and people asking KIP questions. Use descriptive titles, explain unfamiliar terms and keep each page focused on a clear topic.

For procedures, include the purpose, prerequisites, steps and expected result. Where relevant, identify the responsible team and when the information was last reviewed. Avoid storing passwords, API keys or other secrets in documentation.

After publishing or updating a page in a connected source, sync that source with the knowledge base. Once the sync completes successfully, test a question whose answer appears in the updated page. Publishing a change in Confluence alone does not immediately update KIP’s searchable knowledge.

## Access to knowledge

The current setup does not pass Confluence user or group information to Bedrock or apply individual Confluence permissions when answering questions. All authorized users of a KIP deployment can receive answers based on that deployment’s approved knowledge.

Only connect content that is appropriate for everyone authorized to use that deployment. A page’s Confluence restrictions should not be treated as a separate protection for answers delivered through KIP.

## Growing this space

The following supporting pages can be added as the platform and its documentation grow:

- **Platform architecture:** the main components and how they work together.
- **Deploying KIP for your team:** account preparation, deployment configuration and validation.
- **Knowledge sources:** which spaces and content are approved for each deployment.
- **Knowledge Sources and Synchronization:** how content is selected, synchronized and verified.
- **Upgrading your deployment:** adopting shared platform releases while preserving team-specific configuration.
- **Using KIP:** example questions, follow-ups and guidance for different readers.
- **Operations and troubleshooting:** syncing content, checking failures and resolving common issues.
- **Frequently asked questions:** recurring questions with reviewed answers.

These are suggested additions, not a list of guides already available in this space.

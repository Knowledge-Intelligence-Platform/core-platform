# Getting Started with KIP

Use this guide to prepare for adopting KIP or to start using an existing KIP-based assistant. For background on the shared platform and its separate-deployment model, read **KIP Overview**.

## For teams adopting KIP

KIP provides the shared code; your team provides the environment and knowledge. Before deployment, agree on:

- **Purpose:** the application or organizational topics your assistant should cover.
- **AWS environment:** the account and region where your team will run KIP, with the required Bedrock model access and resource permissions.
- **Knowledge sources:** the documentation approved for everyone who will use your deployment.
- **Configuration:** your deployment inputs, knowledge-base settings and team-specific source mappings, kept separate from the core code.
- **Access and ownership:** who can use the assistant and who maintains its content and deployment.

The current integration uses Confluence through Amazon Bedrock Knowledge Bases. Amazon S3 content is also an intended source option, but its connector configuration and retrieval need to be validated for your deployment before use.

After the environment is deployed and its content is synced, test questions with known answers from your own documentation. Also check that unauthenticated requests are rejected and that questions outside the documented scope do not produce unsupported answers.

This is an adoption checklist, not a complete deployment procedure. KIP’s example deployment does not automatically provision another team’s AWS account or knowledge sources.

## For users of an existing deployment

### Access KIP

Open the KIP interface provided for your environment and authenticate as required. If you have not received access details, ask the team managing your KIP deployment.

### Ask your first question

Ask a specific question about your team’s connected documentation, including the topic or process you want to understand. For example:

- What does Application A do?
- What are the documented steps for getting access to Application A?
- Where can I find the troubleshooting guidance for Application A?

Replace “Application A” with your application’s name. These questions require supporting content in your deployment’s knowledge base.

If you are using KIP’s own example deployment, you can instead start with questions covered by the platform overview:

- What is the Knowledge Intelligence Platform?
- What problem does KIP solve?
- Who is KIP intended for?
- How does KIP use Confluence documentation?
- What are the limitations of KIP?

The overview must be published in a connected source and synced before KIP can use it to answer questions about itself. Other teams’ assistants do not automatically know about KIP or any content outside their own configured knowledge base.

### Make your question clear

Include what you need and how you would like it explained. For example:

- “Explain what Application A does in simple terms.”
- “Summarize the documented access-request process for Application A.”
- “What prerequisites are documented for this process?” Include the name of the process you mean.

Avoid including passwords, API keys or other secrets in your questions.

### Ask a follow-up

Continue in the same conversation if you need clarification. You can ask KIP to explain an unfamiliar term, simplify an answer or expand on a documented step.

KIP still needs supporting documentation for follow-up answers. Asking for more detail does not give it access to information outside its connected knowledge sources.

### Check the answer

AI-generated answers can be incomplete or incorrect. Check the original documentation before taking actions that affect services, security or other people.

If KIP says it does not have enough information to answer reliably, try naming the topic more clearly. If the information is documented but still unavailable, ask the team managing the knowledge source to check that the page is included and its latest changes have been synced.

As more documentation is added to your deployment’s connected sources, you can ask about the processes and capabilities it describes. New and updated content must be published or uploaded and synced before KIP can use it.

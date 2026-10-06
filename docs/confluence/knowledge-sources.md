# Knowledge Sources and Synchronization

## Purpose

Knowledge sources are the approved documents that an assistant built on KIP can use when answering questions. The quality, scope and freshness of those sources directly affect the answers users receive.

Each KIP deployment should connect only the content intended for its users. A source connected to one deployment is not automatically available to another deployment.

## Supported and intended sources

### Confluence

The current KIP integration uses an Amazon Bedrock Knowledge Bases Confluence connector. An adopting team can select the Confluence content that forms the approved corpus for its deployment.

Connector credentials are stored in the configured AWS secret-management service. The KIP application does not read those credentials directly.

The current setup does not send Confluence user or group information to Bedrock retrieval and does not apply individual Confluence permissions when generating answers. A deployment should therefore connect only content suitable for all authorized users of that deployment.

### Amazon S3

Amazon S3 is an intended source option for teams that maintain approved documents in S3. The S3 connector, bucket layout, permissions, synchronization and retrieval behavior must be configured and validated for the deployment before it is considered ready for use.

Do not assume that a document uploaded to an arbitrary S3 bucket is available to KIP. The bucket, prefix, permissions and Knowledge Base data source must be explicitly configured.

## Choosing content

Prefer content that is:

- Approved for the intended users.
- Current and maintained by a known owner.
- Clear about its purpose and scope.
- Organized around one topic or process per page where practical.
- Explicit about prerequisites, steps, expected results and exceptions.

Do not connect passwords, API keys, private credentials or content that should not be shared with all users of the deployment.

## How synchronization works

1. The team publishes or uploads approved source content.
2. The configured Bedrock Knowledge Base data source is synchronized.
3. Bedrock parses the content, creates chunks and updates the searchable index.
4. KIP retrieves relevant passages when a user asks a question.
5. The configured model generates an answer from the question and retrieved passages.

Publishing a change in the source does not make it immediately searchable. The source must complete a successful synchronization first.

## Keeping content useful for retrieval

Use descriptive page titles and explain acronyms or specialized terms. Put important details in the page content rather than relying only on navigation labels or visual placement.

For procedures, include the purpose, prerequisites, steps, expected result, common failures and owner. Include review dates where they help readers judge whether the information is current.

Keep related information together when it is normally needed to answer the same question. Split very broad pages when unrelated subjects make retrieval ambiguous.

## Verifying an update

After changing source content:

1. Confirm the page or file was published successfully.
2. Start or wait for the Knowledge Base synchronization job.
3. Confirm that the job completed successfully.
4. Ask a question whose answer appears in the changed content.
5. Compare the answer with the original source.

If the answer is missing, check that the content is within the configured source scope, the synchronization completed, the page is readable by the connector and the question uses terms present in the documentation.

## Source ownership

Each deployment should have an owner for its source configuration and an owner for the content itself. Source owners are responsible for connector credentials, scope and synchronization. Content owners are responsible for accuracy, review and removal of outdated information.

The KIP platform team maintains the reusable retrieval and application capabilities. It does not own the accuracy of another team’s application documentation.

## Boundaries and limitations

KIP answers from retrieved source passages. It does not automatically know about content outside the connected Knowledge Base, current live infrastructure state or unpublished changes.

If there is not enough supporting information, KIP should state that it cannot answer reliably. Users should check the original source before taking actions that affect services, security or other people.

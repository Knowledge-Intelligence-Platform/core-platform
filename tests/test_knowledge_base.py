from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import pytest
from botocore.stub import Stubber

from app.knowledge_base import KnowledgeBase, KnowledgeBaseUnavailableError


@pytest.fixture
def kb() -> Iterator[tuple[KnowledgeBase, Stubber, Stubber]]:
    session = boto3.Session(
        aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1"
    )
    runtime = session.client("bedrock-agent-runtime")
    control = session.client("bedrock-agent")
    knowledge = KnowledgeBase(
        region="us-east-1",
        knowledge_base_id="ABCDEFGHIJ",
        data_source_id="KLMNOPQRST",
        runtime=runtime,
        control=control,
    )
    with Stubber(runtime) as retrieval, Stubber(control) as management:
        yield knowledge, retrieval, management
        retrieval.assert_no_pending_responses()
        management.assert_no_pending_responses()
    knowledge.close()


def retrieval_request() -> dict[str, object]:
    return {
        "knowledgeBaseId": "ABCDEFGHIJ",
        "retrievalQuery": {"text": "What is the platform?"},
        "retrievalConfiguration": {"managedSearchConfiguration": {"numberOfResults": 5}},
    }


def test_retrieval_preserves_source_without_sending_user_identity(kb) -> None:
    knowledge, runtime, _ = kb
    runtime.add_response(
        "retrieve",
        {
            "retrievalResults": [
                {
                    "content": {"type": "TEXT", "text": "Approved platform overview."},
                    "location": {
                        "type": "CONFLUENCE",
                        "confluenceLocation": {"url": "https://example.atlassian.net/wiki/123"},
                    },
                    "metadata": {"title": "Platform overview"},
                    "score": 0.8,
                }
            ]
        },
        retrieval_request(),
    )
    result = knowledge.search("What is the platform?", 5)
    assert len(result) == 1
    assert result[0].source_id == "S1"
    assert result[0].chunk.title == "Platform overview"
    assert result[0].chunk.source_location == "https://example.atlassian.net/wiki/123"
    assert result[0].chunk.text == "Approved platform overview."


def test_empty_results_are_not_retried(kb) -> None:
    knowledge, runtime, _ = kb
    runtime.add_response("retrieve", {"retrievalResults": []}, retrieval_request())
    assert knowledge.search("What is the platform?", 5) == ()


def test_empty_question_does_not_call_aws(kb) -> None:
    knowledge, _, _ = kb
    assert knowledge.search(" ", 5) == ()


def test_retrieval_failure_is_not_an_empty_answer(kb) -> None:
    knowledge, runtime, _ = kb
    runtime.add_client_error(
        "retrieve", "AccessDeniedException", expected_params=retrieval_request()
    )
    with pytest.raises(KnowledgeBaseUnavailableError):
        knowledge.search("What is the platform?", 5)


def test_non_text_results_are_not_used_as_grounding(kb) -> None:
    knowledge, runtime, _ = kb
    runtime.add_response(
        "retrieve",
        {"retrievalResults": [{"content": {"type": "IMAGE", "byteContent": "aW1hZ2U="}}]},
        retrieval_request(),
    )
    assert knowledge.search("What is the platform?", 5) == ()


def test_readiness_reports_permission_failure(kb) -> None:
    knowledge, _, control = kb
    control.add_client_error(
        "get_knowledge_base",
        "AccessDeniedException",
        expected_params={"knowledgeBaseId": "ABCDEFGHIJ"},
    )
    assert knowledge.reachable() is False


def test_sync_returns_a_job_without_waiting(kb) -> None:
    knowledge, _, control = kb
    now = datetime.now(UTC)
    control.add_response(
        "start_ingestion_job",
        {
            "ingestionJob": {
                "knowledgeBaseId": "ABCDEFGHIJ",
                "dataSourceId": "KLMNOPQRST",
                "ingestionJobId": "1234567890",
                "status": "STARTING",
                "startedAt": now,
                "updatedAt": now,
            }
        },
        {"knowledgeBaseId": "ABCDEFGHIJ", "dataSourceId": "KLMNOPQRST"},
    )
    result = knowledge.run()
    assert result.ingestion_job_id == "1234567890"
    assert result.status == "STARTING"


def test_sync_uses_stable_token_and_can_poll_job(kb) -> None:
    knowledge, _, control = kb
    now = datetime.now(UTC)
    job = {
        "knowledgeBaseId": "ABCDEFGHIJ",
        "dataSourceId": "KLMNOPQRST",
        "ingestionJobId": "1234567890",
        "status": "COMPLETE",
        "startedAt": now,
        "updatedAt": now,
    }
    control.add_response(
        "start_ingestion_job",
        {"ingestionJob": job},
        {
            "knowledgeBaseId": "ABCDEFGHIJ",
            "dataSourceId": "KLMNOPQRST",
            "clientToken": "a" * 64,
        },
    )
    control.add_response(
        "get_ingestion_job",
        {"ingestionJob": job},
        {
            "knowledgeBaseId": "ABCDEFGHIJ",
            "dataSourceId": "KLMNOPQRST",
            "ingestionJobId": "1234567890",
        },
    )
    assert knowledge.run(client_token="a" * 64).status == "COMPLETE"
    assert knowledge.sync_status("1234567890").status == "COMPLETE"


def test_source_inspection_returns_status_without_credentials(kb) -> None:
    knowledge, _, control = kb
    now = datetime.now(UTC)
    control.add_response(
        "get_data_source",
        {
            "dataSource": {
                "knowledgeBaseId": "ABCDEFGHIJ",
                "dataSourceId": "KLMNOPQRST",
                "name": "KIP docs",
                "status": "AVAILABLE",
                "createdAt": now,
                "updatedAt": now,
                "dataSourceConfiguration": {
                    "type": "S3",
                    "s3Configuration": {"bucketArn": "arn:aws:s3:::private-source-location"},
                },
            }
        },
        {"knowledgeBaseId": "ABCDEFGHIJ", "dataSourceId": "KLMNOPQRST"},
    )
    control.add_response(
        "list_ingestion_jobs",
        {"ingestionJobSummaries": []},
        {
            "knowledgeBaseId": "ABCDEFGHIJ",
            "dataSourceId": "KLMNOPQRST",
            "maxResults": 1,
            "sortBy": {"attribute": "STARTED_AT", "order": "DESCENDING"},
        },
    )
    assert knowledge.source_status() == {
        "knowledge_base_id": "ABCDEFGHIJ",
        "data_source_id": "KLMNOPQRST",
        "source_status": "AVAILABLE",
        "latest_job": None,
    }


def test_sync_requires_a_configured_data_source(kb) -> None:
    knowledge, _, _ = kb
    knowledge.data_source_id = ""
    with pytest.raises(ValueError):
        knowledge.run()

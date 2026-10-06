from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.models import Chunk, SearchResult, SyncJob

if TYPE_CHECKING:
    from mypy_boto3_bedrock_agent import AgentsforBedrockClient
    from mypy_boto3_bedrock_agent_runtime import AgentsforBedrockRuntimeClient


class KnowledgeBaseUnavailableError(RuntimeError):
    pass


class KnowledgeBase:
    def __init__(
        self,
        *,
        region: str,
        knowledge_base_id: str,
        data_source_id: str,
        runtime: AgentsforBedrockRuntimeClient | None = None,
        control: AgentsforBedrockClient | None = None,
    ) -> None:
        config = Config(connect_timeout=5, read_timeout=60, retries={"mode": "standard"})
        self.runtime = runtime or boto3.client(
            "bedrock-agent-runtime", region_name=region, config=config
        )
        self.control = control or boto3.client("bedrock-agent", region_name=region, config=config)
        self.knowledge_base_id = knowledge_base_id
        self.data_source_id = data_source_id

    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]:
        if not query.strip():
            return ()
        try:
            response = self.runtime.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query[:20000]},
                retrievalConfiguration={"managedSearchConfiguration": {"numberOfResults": limit}},
            )
        except (BotoCoreError, ClientError) as exc:
            raise KnowledgeBaseUnavailableError(
                "Knowledge retrieval is temporarily unavailable."
            ) from exc
        results: list[SearchResult] = []
        for item in response.get("retrievalResults", []):
            result = _search_result(cast(Mapping[str, object], item), len(results) + 1)
            if result is not None:
                results.append(result)
        return tuple(results)

    def reachable(self) -> bool:
        try:
            response = self.control.get_knowledge_base(knowledgeBaseId=self.knowledge_base_id)
        except BotoCoreError, ClientError:
            return False
        return response["knowledgeBase"]["status"] == "ACTIVE"

    def run(self, *, client_token: str | None = None) -> SyncJob:
        if not self.data_source_id:
            raise ValueError("A knowledge base data source ID is required to start a sync.")
        try:
            if client_token is None:
                response = self.control.start_ingestion_job(
                    knowledgeBaseId=self.knowledge_base_id, dataSourceId=self.data_source_id
                )
            else:
                response = self.control.start_ingestion_job(
                    knowledgeBaseId=self.knowledge_base_id,
                    dataSourceId=self.data_source_id,
                    clientToken=client_token,
                )
        except (BotoCoreError, ClientError) as exc:
            raise KnowledgeBaseUnavailableError("The knowledge sync could not be started.") from exc
        job = response["ingestionJob"]
        return SyncJob(
            knowledge_base_id=job["knowledgeBaseId"],
            data_source_id=job["dataSourceId"],
            ingestion_job_id=job["ingestionJobId"],
            status=job["status"],
        )

    def sync_status(self, job_id: str) -> SyncJob:
        try:
            response = self.control.get_ingestion_job(
                knowledgeBaseId=self.knowledge_base_id,
                dataSourceId=self.data_source_id,
                ingestionJobId=job_id,
            )
        except (BotoCoreError, ClientError) as exc:
            raise KnowledgeBaseUnavailableError("The sync status is unavailable.") from exc
        job = response["ingestionJob"]
        return SyncJob(
            knowledge_base_id=job["knowledgeBaseId"],
            data_source_id=job["dataSourceId"],
            ingestion_job_id=job["ingestionJobId"],
            status=job["status"],
        )

    def source_status(self) -> dict[str, object]:
        try:
            source = self.control.get_data_source(
                knowledgeBaseId=self.knowledge_base_id, dataSourceId=self.data_source_id
            )["dataSource"]
            jobs = self.control.list_ingestion_jobs(
                knowledgeBaseId=self.knowledge_base_id,
                dataSourceId=self.data_source_id,
                maxResults=1,
                sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
            ).get("ingestionJobSummaries", [])
        except (BotoCoreError, ClientError) as exc:
            raise KnowledgeBaseUnavailableError("The source status is unavailable.") from exc
        return {
            "knowledge_base_id": self.knowledge_base_id,
            "data_source_id": self.data_source_id,
            "source_status": source["status"],
            "latest_job": {
                "ingestion_job_id": jobs[0]["ingestionJobId"],
                "status": jobs[0]["status"],
                "started_at": jobs[0]["startedAt"].isoformat(),
            }
            if jobs
            else None,
        }

    def close(self) -> None:
        self.runtime.close()
        self.control.close()


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, dict) else {}


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _search_result(item: Mapping[str, object], position: int) -> SearchResult | None:
    content = _mapping(item.get("content"))
    text = content.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    location = _mapping(item.get("location"))
    metadata = _mapping(item.get("metadata"))
    url = ""
    for key in ("confluenceLocation", "webLocation", "s3Location", "customDocumentLocation"):
        details = _mapping(location.get(key))
        value = details.get("url") or details.get("uri") or details.get("id")
        if isinstance(value, str) and value:
            url = value
            break
    if not url:
        value = metadata.get("x-amz-bedrock-kb-source-uri") or item.get("documentId")
        url = value if isinstance(value, str) else ""
    document_id = str(item.get("documentId") or url or hashlib.sha256(text.encode()).hexdigest())
    title = (
        metadata.get("_document_title")
        or metadata.get("title")
        or metadata.get("document_title")
        or url
        or "Knowledge document"
    )
    space = metadata.get("_cf_space_name")
    page = metadata.get("x-amz-bedrock-kb-document-page-number")
    score = item.get("score", 0.0)
    return SearchResult(
        source_id=f"S{position}",
        chunk=Chunk(
            chunk_id=hashlib.sha256(f"{document_id}\n{text}".encode()).hexdigest(),
            document_id=document_id,
            title=str(title),
            text=text,
            source_location=url,
            page_number=int(page) if isinstance(page, int | float) and page >= 1 else None,
            space=space if isinstance(space, str) and space else None,
            last_updated_at=_timestamp(metadata.get("_last_updated_at")),
        ),
        score=float(score) if isinstance(score, int | float) else 0.0,
    )

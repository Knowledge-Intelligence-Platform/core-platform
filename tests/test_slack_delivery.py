"""Slack delivery: diagram blocks, and never losing an answer to a bad block."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError
from slack_sdk.errors import SlackApiError

from app.models import KnowledgeAnswer, MindMap, MindMapBranch
from app.slack import (
    DiagramStore,
    SlackIntegration,
    _delivery_attempts,
    _diagram_title,
    _flow_nodes,
)

PLATFORM = "Example Platform"
FLOW = "Request a cluster\n↓\nAwait approval\n↓\nDeploy the workload"


def test_a_stored_flow_splits_back_into_its_nodes() -> None:
    assert _flow_nodes(FLOW) == ("Request a cluster", "Await approval", "Deploy the workload")


def test_source_markers_never_reach_a_diagram_node() -> None:
    assert _flow_nodes("Request [S1]\n↓\nApprove [S2]") == ("Request", "Approve")


@pytest.mark.parametrize(
    ("response_type", "expected"),
    [
        ("onboarding", "Your onboarding journey"),
        ("comparison", "Service comparison"),
        ("mapping", "Connected knowledge map"),
        ("general", f"{PLATFORM} high-level view"),
    ],
)
def test_the_diagram_is_titled_for_the_answer(response_type: str, expected: str) -> None:
    assert _diagram_title(response_type, PLATFORM) == expected


DIAGRAM_URL = "https://bucket.s3.ap-south-1.amazonaws.com/diagrams/slack/x.png?sig=abc"


def test_a_published_diagram_is_embedded_in_the_message() -> None:
    result = KnowledgeAnswer(answer="Here is the flow.", visual=FLOW, response_type="mapping")
    blocks = SlackIntegration._blocks(
        result, result.answer, PLATFORM, DIAGRAM_URL, "Connected knowledge map"
    )

    images = [block for block in blocks if block.get("type") == "image"]
    assert len(images) == 1
    assert images[0]["image_url"] == DIAGRAM_URL
    assert images[0]["alt_text"] == "Connected knowledge map"
    assert "slack_file" not in images[0]


def test_a_failed_publish_falls_back_to_text_cards() -> None:
    result = KnowledgeAnswer(answer="Here is the flow.", visual=FLOW, response_type="mapping")
    blocks = SlackIntegration._blocks(
        result, result.answer, PLATFORM, None, "Connected knowledge map"
    )

    assert not any(block.get("type") == "image" for block in blocks)
    rendered = json.dumps(blocks, ensure_ascii=False)
    assert "Request a cluster" in rendered
    assert "Await approval" in rendered


def test_an_answer_without_a_flow_has_neither() -> None:
    result = KnowledgeAnswer(answer="Just an answer.")
    blocks = SlackIntegration._blocks(result, result.answer, PLATFORM)

    assert not any(block.get("type") == "image" for block in blocks)
    assert "Request a cluster" not in json.dumps(blocks)


def test_follow_ups_and_feedback_survive_a_diagram() -> None:
    result = KnowledgeAnswer(
        answer="Here is the flow.",
        visual=FLOW,
        suggested_questions=("What happens after approval?",),
        response_type="mapping",
    )
    rendered = json.dumps(
        SlackIntegration._blocks(result, result.answer, PLATFORM, DIAGRAM_URL),
        ensure_ascii=False,
    )
    assert "What happens after approval?" in rendered
    assert "Was this answer helpful?" in rendered


def test_a_rejected_image_block_never_costs_the_answer() -> None:
    blocks: tuple[dict[str, Any], ...] = (
        {"type": "section", "block_id": "answer"},
        {"type": "image", "slack_file": {"id": "F1"}, "alt_text": "flow"},
        {"type": "actions", "block_id": "feedback"},
    )
    attempts = _delivery_attempts(blocks)

    assert attempts[0] == blocks
    assert all(block.get("type") != "image" for block in attempts[1])
    assert len(attempts[1]) == 2
    assert attempts[-1] == ()


def test_blocks_without_an_image_are_not_retried_identically() -> None:
    blocks: tuple[dict[str, Any], ...] = ({"type": "section", "block_id": "answer"},)
    attempts = _delivery_attempts(blocks)

    assert attempts[0] == blocks
    assert attempts[-1] == ()
    assert len(attempts) == 2


def test_an_empty_message_has_a_single_attempt() -> None:
    assert _delivery_attempts(()) == ((),)


class FakeS3:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[key])}


def make_store(client: FakeS3, base_url: str = "https://api.example.invalid") -> DiagramStore:
    store = DiagramStore.__new__(DiagramStore)
    store.client = client
    store.bucket = "knowledge-intelligence-platform"
    store.prefix = "diagrams/slack"
    store.base_url = base_url
    return store


def test_a_published_diagram_is_served_by_the_application() -> None:
    client = FakeS3()
    url = make_store(client).publish(BytesIO(b"\x89PNG\r\n\x1a\n"))

    assert url is not None
    assert url.startswith("https://api.example.invalid/diagrams/")
    assert url.endswith(".png")
    assert len(client.objects) == 1
    key = next(iter(client.objects))
    assert key.startswith("diagrams/slack/")
    assert key.endswith(".png")


def test_a_published_diagram_can_be_read_back() -> None:
    client = FakeS3()
    store = make_store(client)
    url = store.publish(BytesIO(b"image-bytes"))

    assert url is not None
    diagram_id = url.rsplit("/", 1)[-1].removesuffix(".png")
    assert store.read(diagram_id) == b"image-bytes"


def test_an_unknown_diagram_reads_as_missing() -> None:
    assert make_store(FakeS3()).read("does-not-exist") is None


def test_two_diagrams_never_share_a_key() -> None:
    client = FakeS3()
    store = make_store(client)
    store.publish(BytesIO(b"one"))
    store.publish(BytesIO(b"two"))

    assert len(client.objects) == 2


def test_a_storage_failure_is_not_fatal() -> None:
    assert make_store(FakeS3(fail=True)).publish(BytesIO(b"x")) is None


def test_without_a_public_url_no_image_is_offered() -> None:
    assert make_store(FakeS3(), base_url="").publish(BytesIO(b"x")) is None


MINDMAP = MindMap(
    center="KIP",
    branches=(
        MindMapBranch(label="Purpose", items=("Compliance",)),
        MindMapBranch(label="Coverage", items=("UK",)),
    ),
)


def test_a_map_is_embedded_like_any_other_diagram() -> None:
    result = KnowledgeAnswer(answer="KIP covers several areas.", mindmap=MINDMAP)
    blocks = SlackIntegration._blocks(
        result, result.answer, PLATFORM, DIAGRAM_URL, "Knowledge map"
    )

    images = [block for block in blocks if block.get("type") == "image"]
    assert len(images) == 1
    assert images[0]["image_url"] == DIAGRAM_URL
    assert images[0]["alt_text"] == "Knowledge map"


def test_a_map_that_could_not_be_rendered_adds_no_flow_cards() -> None:
    result = KnowledgeAnswer(answer="KIP covers several areas.", mindmap=MINDMAP)
    blocks = SlackIntegration._blocks(
        result, result.answer, PLATFORM, None, "Knowledge map"
    )

    assert not any(block.get("type") == "image" for block in blocks)
    assert "Purpose" not in json.dumps(blocks)


class RejectingSlackClient:
    """Rejects any message carrying an image block, the way Slack does."""

    def __init__(self) -> None:
        self.attempts: list[tuple[dict[str, Any], ...]] = []

    def chat_postMessage(self, **kwargs: Any) -> dict[str, str]:
        blocks = tuple(kwargs.get("blocks") or ())
        self.attempts.append(blocks)
        if any(block.get("type") == "image" for block in blocks):
            raise SlackApiError(
                "invalid_blocks", {"ok": False, "error": "invalid_blocks"}
            )
        return {"ts": "1700000000.000100"}


def _integration_with(client: RejectingSlackClient) -> SlackIntegration:
    integration = SlackIntegration.__new__(SlackIntegration)
    integration.client = client  # type: ignore[assignment]
    integration.maximum_message_length = 4000
    return integration


def test_posting_a_rejected_image_block_still_delivers_the_answer() -> None:
    client = RejectingSlackClient()
    blocks: tuple[dict[str, Any], ...] = (
        {"type": "section", "block_id": "answer"},
        {"type": "image", "image_url": DIAGRAM_URL, "alt_text": "flow"},
    )


    timestamp = _integration_with(client)._post("C1", "1.0", "The answer.", blocks)

    assert timestamp == "1700000000.000100"
    assert len(client.attempts) == 2
    assert all(block.get("type") != "image" for block in client.attempts[1])


def test_posting_a_message_without_blocks_is_attempted_once() -> None:
    client = RejectingSlackClient()

    timestamp = _integration_with(client)._post("C1", "1.0", "The answer.", ())

    assert timestamp == "1700000000.000100"
    assert len(client.attempts) == 1

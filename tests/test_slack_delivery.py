"""Slack delivery: diagram blocks, and never losing an answer to a bad block."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.models import KnowledgeAnswer, MindMap, MindMapBranch
from app.slack import (
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


def test_a_flow_is_delivered_as_text_cards() -> None:
    result = KnowledgeAnswer(answer="Here is the flow.", visual=FLOW, response_type="mapping")
    blocks = SlackIntegration._blocks(result, result.answer, PLATFORM)

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
        SlackIntegration._blocks(result, result.answer, PLATFORM),
        ensure_ascii=False,
    )
    assert "What happens after approval?" in rendered
    assert "Was this answer helpful?" in rendered


def test_blocks_without_an_image_are_not_retried_identically() -> None:
    blocks: tuple[dict[str, Any], ...] = ({"type": "section", "block_id": "answer"},)
    attempts = _delivery_attempts(blocks)

    assert attempts[0] == blocks
    assert attempts[-1] == ()
    assert len(attempts) == 2


def test_an_empty_message_has_a_single_attempt() -> None:
    assert _delivery_attempts(()) == ((),)


MINDMAP = MindMap(
    center="KIP",
    branches=(
        MindMapBranch(label="Purpose", items=("Compliance",)),
        MindMapBranch(label="Coverage", items=("UK",)),
    ),
)


def test_a_map_preserves_its_branches_as_text() -> None:
    result = KnowledgeAnswer(answer="KIP covers several areas.", mindmap=MINDMAP)
    blocks = SlackIntegration._blocks(result, result.answer, PLATFORM)

    assert not any(block.get("type") == "image" for block in blocks)
    assert "Purpose" in json.dumps(blocks)
    assert "Compliance" in json.dumps(blocks)
    assert "Coverage" in json.dumps(blocks)


class RejectingSlackClient:
    """Rejects rich blocks while accepting the plain-text fallback."""

    def __init__(self) -> None:
        self.attempts: list[tuple[dict[str, Any], ...]] = []

    def chat_postMessage(self, **kwargs: Any) -> dict[str, str]:
        blocks = tuple(kwargs.get("blocks") or ())
        self.attempts.append(blocks)
        if blocks:
            raise SlackApiError("invalid_blocks", {"ok": False, "error": "invalid_blocks"})
        return {"ts": "1700000000.000100"}


def _integration_with(client: RejectingSlackClient) -> SlackIntegration:
    integration = SlackIntegration.__new__(SlackIntegration)
    integration.client = cast(WebClient, client)
    integration.maximum_message_length = 4000
    return integration


def test_rejected_blocks_still_deliver_the_plain_answer() -> None:
    client = RejectingSlackClient()
    blocks: tuple[dict[str, Any], ...] = ({"type": "section", "block_id": "answer"},)

    timestamp = _integration_with(client)._post("C1", "1.0", "The answer.", blocks)

    assert timestamp == "1700000000.000100"
    assert len(client.attempts) == 2
    assert client.attempts[1] == ()


def test_posting_a_message_without_blocks_is_attempted_once() -> None:
    client = RejectingSlackClient()

    timestamp = _integration_with(client)._post("C1", "1.0", "The answer.", ())

    assert timestamp == "1700000000.000100"
    assert len(client.attempts) == 1

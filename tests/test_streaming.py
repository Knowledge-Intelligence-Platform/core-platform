"""Progressive delivery: decoding an answer out of a structured-output stream."""

from __future__ import annotations

import json
from typing import Any, cast

import boto3
import pytest
from strands import Agent
from strands.models import BedrockModel

from app.agent import (
    INSUFFICIENT_ANSWER,
    PartialAnswer,
    PlatformKnowledgeAgent,
    _session_id,
)
from tests.conftest import StubSearch, StubStreamingAgent

TRICKY = (
    'Here\'s how onboarding works 🚀\n\n1. Raise a "cluster request" [S1]\n'
    "2. Await ✅ approval\n\tDeploy — runbook.\\path\\to 🧭"
)


@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("chunk_size", [1, 2, 5, 64, 999])
def test_answer_is_recovered_from_any_chunking(ensure_ascii: bool, chunk_size: int) -> None:
    serialized = json.dumps(
        {"answer": TRICKY, "response_type": "onboarding"}, ensure_ascii=ensure_ascii
    )
    partial = PartialAnswer()
    for start in range(0, len(serialized), chunk_size):
        partial.feed(serialized[start : start + chunk_size])
    assert partial.text() == TRICKY


@pytest.mark.parametrize("ensure_ascii", [True, False])
def test_every_intermediate_value_is_a_valid_encodable_prefix(ensure_ascii: bool) -> None:
    """An emoji is a surrogate pair; half of one is not UTF-8 encodable."""
    serialized = json.dumps({"answer": TRICKY}, ensure_ascii=ensure_ascii)
    partial = PartialAnswer()
    for character in serialized:
        partial.feed(character)
        current = partial.text()
        if current is None:
            continue
        assert TRICKY.startswith(current)
        current.encode("utf-8")


def test_nothing_is_emitted_before_the_answer_field_arrives() -> None:
    partial = PartialAnswer()
    partial.feed('{"response_ty')
    assert partial.text() is None


@pytest.mark.parametrize("truncated", ['{"answer":"abc\\u00', '{"answer":"abc\\'])
def test_truncated_escapes_do_not_raise(truncated: str) -> None:
    partial = PartialAnswer()
    partial.feed(truncated)
    partial.text()


def build_agent(search: StubSearch, **options: Any) -> PlatformKnowledgeAgent:
    return PlatformKnowledgeAgent(
        model=BedrockModel(
            model_id="amazon.nova-lite-v1:0",
            boto_session=boto3.Session(
                aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1"
            ),
        ),
        model_id="test-model",
        platform_name="Example Platform",
        search=search,
        maximum_results=5,
        metrics_enabled=False,
        **options,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_harness_preserves_grounding_and_explicit_cache_checkpoint(
    enabled: bool,
    tmp_path,
    monkeypatch,
) -> None:
    from app.agent import cacheable_system_prompt

    monkeypatch.chdir(tmp_path)
    wrapper = build_agent(StubSearch(), prompt_caching_enabled=enabled)
    agent = wrapper._build_agent("cache-test", persist=False)
    assert agent.model is wrapper.model
    assert agent.memory_manager is None
    assert not {
        "shell",
        "read",
        "write",
        "edit",
        "web_fetch",
        "web_search",
        "subagent",
    }.intersection(agent.tool_registry.registry)
    blocks = cacheable_system_prompt(wrapper.instructions, enabled)
    request = wrapper.model.format_request(
        messages=[{"role": "user", "content": [{"text": "A new question with fresh passages"}]}],
        system_prompt_content=blocks if isinstance(blocks, list) else [{"text": blocks}],
    )
    assert any("cachePoint" in item for item in request["system"]) is enabled
    assert all("cachePoint" not in item for item in request["messages"][0]["content"])
    assert request["modelId"] == "amazon.nova-lite-v1:0"
    assert not (tmp_path / ".agent").exists()


def test_streaming_returns_the_structured_answer(answer_payload: dict[str, Any]) -> None:
    agent = build_agent(StubSearch())
    conversation = agent._for("C1:1.0")
    conversation.agent = StubStreamingAgent(answer_payload)  # type: ignore[assignment]
    result = agent.answer_stream("How do I onboard?", conversation_id="C1:1.0")
    assert result.answer == answer_payload["answer"]
    assert result.response_type == "onboarding"
    assert result.visual == "Request\n↓\nApprove\n↓\nDeploy"


def test_partials_are_growing_prefixes(answer_payload: dict[str, Any]) -> None:
    agent = build_agent(StubSearch(), stream_interval_seconds=0.3)
    conversation = agent._for("C2:1.0")
    conversation.agent = StubStreamingAgent(answer_payload)  # type: ignore[assignment]
    seen: list[str] = []
    agent.answer_stream("q", conversation_id="C2:1.0", on_partial=seen.append)
    assert all(answer_payload["answer"].startswith(text) for text in seen)
    assert all(len(a) <= len(b) for a, b in zip(seen, seen[1:], strict=False))


def test_falls_back_to_streamed_text_without_structured_output(
    answer_payload: dict[str, Any],
) -> None:
    agent = build_agent(StubSearch())
    conversation = agent._for("C3:1.0")
    conversation.agent = StubStreamingAgent(answer_payload, emit_structured=False)  # type: ignore[assignment]
    result = agent.answer_stream("q", conversation_id="C3:1.0")
    assert result.answer == answer_payload["answer"]


def test_no_retrieval_refuses_without_calling_the_model() -> None:
    agent = build_agent(StubSearch(results=0))
    conversation = agent._for("C4:1.0")
    conversation.agent = StubStreamingAgent({"answer": "should never be used"})  # type: ignore[assignment]
    result = agent.answer_stream("unknown", conversation_id="C4:1.0")
    assert result.answer == INSUFFICIENT_ANSWER
    assert conversation.agent.prompts == []  # type: ignore[union-attr]


def test_streamed_refusal_is_stripped_of_furniture() -> None:
    drifting = {
        "answer": INSUFFICIENT_ANSWER,
        "response_type": "onboarding",
        "visual_nodes": ["A", "B", "C"],
        "suggested_questions": ["Q1?", "Q2?"],
    }
    agent = build_agent(StubSearch())
    conversation = agent._for("C5:1.0")
    conversation.agent = StubStreamingAgent(drifting)  # type: ignore[assignment]
    result = agent.answer_stream("q", conversation_id="C5:1.0")
    assert result.visual is None
    assert result.suggested_questions == ()
    assert result.response_type == "general"


def test_follow_up_turn_carries_the_previous_question(answer_payload: dict[str, Any]) -> None:
    search = StubSearch()
    agent = build_agent(search)
    conversation = agent._for("C6:1.0")
    conversation.agent = StubStreamingAgent(answer_payload)  # type: ignore[assignment]
    agent.answer_stream("What is KIP Service?", conversation_id="C6:1.0")
    agent.answer_stream("What happens next?", conversation_id="C6:1.0")
    assert "Previous question" not in search.queries[0]
    assert "Previous question in this conversation: What is KIP Service?" in search.queries[1]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("C123ABC:1699.5", "C123ABC-1699-5"), ("thread:C1:U1", "thread-C1-U1"), (":::", "default")],
)
def test_session_ids_are_storage_safe(raw: str, expected: str) -> None:
    assert _session_id(raw) == expected


def test_conversations_are_partitioned_by_verified_identity() -> None:
    alice = PlatformKnowledgeAgent._identity_conversation("shared-thread", "alice@example.com")
    bob = PlatformKnowledgeAgent._identity_conversation("shared-thread", "bob@example.com")
    assert alice != bob
    assert alice == PlatformKnowledgeAgent._identity_conversation(
        "shared-thread", "alice@example.com"
    )
    assert "alice" not in str(alice)
    assert PlatformKnowledgeAgent._identity_conversation(None, "alice@example.com") is None


def test_bedrock_tool_events_deliver_progress(answer_payload: dict[str, Any]) -> None:
    agent = build_agent(StubSearch())
    conversation = agent._for("nova-stream")
    conversation.agent = cast(Agent, StubStreamingAgent(answer_payload, tool_events=True))
    seen: list[str] = []
    answer = agent.answer_stream(
        "How do I onboard?", conversation_id="nova-stream", on_partial=seen.append
    )
    assert seen
    assert all(answer_payload["answer"].startswith(partial) for partial in seen)
    assert answer.answer == answer_payload["answer"]

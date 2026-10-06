"""The answer contract is enforced in code, not merely requested in the prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import (
    INSUFFICIENT_ANSWER,
    IntelligentBranch,
    IntelligentResponse,
    PlatformKnowledgeAgent,
    is_refusal,
    public_answer,
)

normalise = PlatformKnowledgeAgent._knowledge_answer


@pytest.mark.parametrize(
    "variant",
    [
        INSUFFICIENT_ANSWER,
        INSUFFICIENT_ANSWER.rstrip("."),
        INSUFFICIENT_ANSWER.upper(),
        f'"{INSUFFICIENT_ANSWER}"',
        "  I don't have   enough information to answer that reliably.  ",
        "I don’t have enough information to answer that reliably.",
    ],
)
def test_refusal_survives_model_drift(variant: str) -> None:
    assert is_refusal(variant)


def test_answer_merely_mentioning_the_phrase_is_not_a_refusal() -> None:
    assert not is_refusal(
        "I don't have enough information to answer that reliably about cost, "
        "but onboarding works like this."
    )


def test_ordinary_answer_is_not_a_refusal() -> None:
    assert not is_refusal("Onboarding starts with a cluster request.")


def test_refusal_cannot_carry_a_diagram_or_buttons() -> None:
    drifted = IntelligentResponse(
        answer=INSUFFICIENT_ANSWER,
        response_type="onboarding",
        visual_nodes=("Request", "Approve", "Deploy"),
        suggested_questions=("How do I start?", "What is KIP Service?"),
    )
    result = normalise(drifted)
    assert result.answer == INSUFFICIENT_ANSWER
    assert result.visual is None
    assert result.suggested_questions == ()
    assert result.response_type == "general"


def test_drifted_refusal_is_canonicalised() -> None:
    drifted = IntelligentResponse(answer=f'  "{INSUFFICIENT_ANSWER.upper()}" ')
    assert normalise(drifted).answer == INSUFFICIENT_ANSWER


def test_blank_answer_degrades_to_a_refusal() -> None:
    assert normalise(IntelligentResponse(answer="   ")).answer == INSUFFICIENT_ANSWER


def test_follow_up_already_in_the_answer_is_dropped() -> None:
    response = IntelligentResponse(
        answer="Raise a cluster request, then await approval. What happens after approval?",
        suggested_questions=("What happens after approval?", "How long does approval take?"),
    )
    assert normalise(response).suggested_questions == ("How long does approval take?",)


def test_duplicate_follow_ups_collapse() -> None:
    response = IntelligentResponse(
        answer="Onboarding overview.",
        suggested_questions=(
            "What is KIP Service?",
            "What is KIP Service?",
            "Where is the runbook?",
        ),
    )
    assert normalise(response).suggested_questions == (
        "What is KIP Service?",
        "Where is the runbook?",
    )


def test_a_single_node_is_not_a_flow() -> None:
    assert normalise(IntelligentResponse(answer="x", visual_nodes=("Only step",))).visual is None


def test_repeated_and_blank_nodes_are_cleaned() -> None:
    response = IntelligentResponse(answer="x", visual_nodes=("A", "A", "   ", "B"))
    assert normalise(response).visual == "A\n↓\nB"


def test_source_markers_are_stripped_from_nodes_and_follow_ups() -> None:
    response = IntelligentResponse(
        answer="x",
        visual_nodes=("Request [S1]", "Approve [S2]"),
        suggested_questions=("What next? [S1]",),
    )
    result = normalise(response)
    assert result.visual == "Request\n↓\nApprove"
    assert result.suggested_questions == ("What next?",)


def test_healthy_answer_passes_through_unchanged() -> None:
    response = IntelligentResponse(
        answer="Onboarding starts with a cluster request 🚀",
        response_type="onboarding",
        visual_nodes=("Request", "Approve", "Deploy"),
        suggested_questions=("What happens after approval?",),
    )
    result = normalise(response)
    assert result.answer == response.answer
    assert result.response_type == "onboarding"
    assert result.visual == "Request\n↓\nApprove\n↓\nDeploy"
    assert result.suggested_questions == ("What happens after approval?",)


def test_public_answer_removes_internal_markers() -> None:
    assert public_answer("Do this [S1]. Then that [S2].") == "Do this. Then that."


@pytest.mark.parametrize(
    "preamble",
    [
        "Based on the information provided,",
        "Based on the provided information,",
        "From the available information:",
        "From the information available -",
        "Using the approved KIP knowledge available in the conversation,",
    ],
)
def test_public_answer_removes_backend_preamble(preamble: str) -> None:
    assert public_answer(f"{preamble} do this.") == "do this."


def test_public_answer_keeps_ordinary_text() -> None:
    assert public_answer("Based on your question, do this.") == "Based on your question, do this."


def test_instructions_use_the_refusal_constant() -> None:
    from app.agent import instructions

    rendered = instructions("Example Platform")
    assert INSUFFICIENT_ANSWER in rendered
    assert "{" not in rendered and "}" not in rendered


def test_instructions_ship_beside_the_package() -> None:
    from app.agent import INSTRUCTIONS_PATH

    assert INSTRUCTIONS_PATH.name == "instructions.md"
    assert INSTRUCTIONS_PATH.parent.name == "app"
    assert INSTRUCTIONS_PATH.is_file()


def test_a_literal_brace_in_the_instructions_is_harmless(tmp_path: Path) -> None:
    from app.agent import INSUFFICIENT_ANSWER as refusal

    source = tmp_path / "instructions.md"
    source.write_text('Return JSON like {"answer": "x"}. Refuse with "{INSUFFICIENT_ANSWER}"')
    rendered = source.read_text().replace("{INSUFFICIENT_ANSWER}", refusal)

    assert refusal in rendered
    assert '{"answer": "x"}' in rendered


def test_every_structured_field_is_named_in_the_instructions() -> None:
    from app.agent import IntelligentResponse, instructions

    rendered = instructions("Example Platform")
    for field in IntelligentResponse.model_fields:
        assert field in rendered, field


def test_the_prompt_names_no_platform_of_its_own() -> None:
    """A second tenant needs a registry, not a fork of the prompt."""
    from app.agent import INSTRUCTIONS_PATH, instructions

    source = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    assert "{PLATFORM_NAME}" in source
    assert "Tenant Zero" in instructions("Tenant Zero")


def branch(label: str, *items: str) -> IntelligentBranch:
    return IntelligentBranch(label=label, items=items)


def test_a_map_needs_a_subject_and_two_branches() -> None:
    response = IntelligentResponse(
        answer="KIP covers several areas.",
        visual_center="KIP",
        visual_branches=(branch("Purpose", "Compliance"), branch("Coverage", "UK")),
    )
    result = normalise(response)
    assert result.mindmap is not None
    assert result.mindmap.center == "KIP"
    assert [item.label for item in result.mindmap.branches] == ["Purpose", "Coverage"]


def test_a_map_without_a_subject_is_dropped() -> None:
    response = IntelligentResponse(
        answer="x",
        visual_center="   ",
        visual_branches=(branch("Purpose", "a"), branch("Coverage", "b")),
    )
    assert normalise(response).mindmap is None


def test_a_single_branch_is_not_a_map() -> None:
    response = IntelligentResponse(
        answer="x", visual_center="KIP", visual_branches=(branch("Purpose", "a"),)
    )
    assert normalise(response).mindmap is None


def test_a_sequence_wins_over_a_map() -> None:
    response = IntelligentResponse(
        answer="x",
        visual_nodes=("Request", "Approve"),
        visual_center="KIP",
        visual_branches=(branch("Purpose", "a"), branch("Coverage", "b")),
    )
    result = normalise(response)
    assert result.visual == "Request\n↓\nApprove"
    assert result.mindmap is None


def test_a_refusal_cannot_carry_a_map() -> None:
    response = IntelligentResponse(
        answer=INSUFFICIENT_ANSWER,
        visual_center="KIP",
        visual_branches=(branch("Purpose", "a"), branch("Coverage", "b")),
    )
    assert normalise(response).mindmap is None


def test_source_markers_never_reach_a_map() -> None:
    response = IntelligentResponse(
        answer="x",
        visual_center="KIP [S1]",
        visual_branches=(branch("Purpose [S2]", "Compliance [S3]"), branch("Coverage", "UK")),
    )
    mindmap = normalise(response).mindmap
    assert mindmap is not None
    assert mindmap.center == "KIP"
    assert mindmap.branches[0].label == "Purpose"
    assert mindmap.branches[0].items == ("Compliance",)


def test_repeated_branches_and_items_collapse() -> None:
    response = IntelligentResponse(
        answer="x",
        visual_center="KIP",
        visual_branches=(
            branch("Purpose", "Compliance", "Compliance", "  "),
            branch("purpose", "ignored"),
            branch("Coverage", "UK"),
        ),
    )
    mindmap = normalise(response).mindmap
    assert mindmap is not None
    assert [item.label for item in mindmap.branches] == ["Purpose", "Coverage"]
    assert mindmap.branches[0].items == ("Compliance",)


def test_an_item_repeating_its_branch_is_dropped() -> None:
    response = IntelligentResponse(
        answer="x",
        visual_center="KIP",
        visual_branches=(branch("Purpose", "purpose", "Compliance"), branch("Coverage", "UK")),
    )
    mindmap = normalise(response).mindmap
    assert mindmap is not None
    assert mindmap.branches[0].items == ("Compliance",)

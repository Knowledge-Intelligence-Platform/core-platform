"""The Slack flow renderer draws the grounded steps and nothing else."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.diagram import (
    MAXIMUM_STEPS,
    RAIL_MAX_STEPS,
    _split_stage,
    _split_step,
    _stages,
    _wrap,
    render_flow,
    render_mindmap,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def size(image: BytesIO) -> tuple[int, int]:
    with Image.open(image) as rendered:
        return rendered.size


def test_a_flow_renders_as_a_png() -> None:
    output = render_flow(("Request a cluster", "Await approval"))
    assert output.getvalue().startswith(PNG_MAGIC)
    width, height = size(output)
    assert width > 400
    assert height > 200


def test_a_longer_journey_makes_a_taller_image() -> None:
    short = size(render_flow(("Request", "Approve")))[1]
    long = size(render_flow(("Request", "Approve", "Deploy", "Validate")))[1]
    assert long > short


def test_a_wordy_step_grows_its_card() -> None:
    plain = size(render_flow(("Request", "Approve")))[1]
    wordy = size(render_flow(("Request " * 40, "Approve")))[1]
    assert wordy > plain


def test_only_the_supported_number_of_steps_is_drawn() -> None:
    capped = size(render_flow(tuple(f"Step {index}" for index in range(20))))[1]
    exact = size(render_flow(tuple(f"Step {index}" for index in range(MAXIMUM_STEPS))))[1]
    assert capped == exact


def test_blank_steps_are_ignored() -> None:
    assert size(render_flow(("Request", "   ", "Approve"))) == size(
        render_flow(("Request", "Approve"))
    )


def test_a_step_detail_is_separated_from_its_headline() -> None:
    assert _split_step("Request a cluster → via the platform form") == (
        "Request a cluster",
        "via the platform form",
    )
    assert _split_step("Build -> Test -> Ship") == ("Build", "Test  ➜  Ship")
    assert _split_step("Request a cluster") == ("Request a cluster", "")


def test_wrapping_never_loses_words() -> None:
    from app.diagram import _font

    text = "Raise an onboarding request with the platform engineering team"
    assert " ".join(_wrap(text, _font(31, bold=True), 300)).split() == text.split()


def test_a_leading_stage_token_becomes_its_own_chip() -> None:
    assert _split_stage("M0 · Confirm scope") == ("M0", "Confirm scope")
    assert _split_stage("Step 2: Approve design") == ("STEP 2", "Approve design")
    assert _split_stage("Confirm scope") == ("", "Confirm scope")
    assert _split_stage("KIP Service · Service") == ("", "KIP Service · Service")


def test_a_long_flow_is_wrapped_into_two_columns() -> None:
    tall = size(render_flow(tuple(f"Step {index}" for index in range(4))))
    wide = size(render_flow(tuple(f"Step {index}" for index in range(8))))
    assert wide[0] > tall[0]
    assert wide[0] > wide[1]


def test_a_short_flow_uses_the_rail_renderer() -> None:
    width, height = size(render_flow(tuple(f"Step {index}" for index in range(RAIL_MAX_STEPS))))

    assert width == 1500
    assert width > height


def test_every_flow_the_rail_draws_stays_landscape() -> None:
    for count in range(2, RAIL_MAX_STEPS + 1):
        steps = tuple(f"Step {index} -> a grounded detail line" for index in range(count))
        width, height = size(render_flow(steps))
        assert width > height, f"{count} steps rendered taller than it is wide"


def test_a_flow_beyond_the_rail_limit_is_wrapped_by_graphviz() -> None:
    rail = size(render_flow(tuple(f"Step {index}" for index in range(RAIL_MAX_STEPS))))
    wrapped = size(render_flow(tuple(f"Step {index}" for index in range(RAIL_MAX_STEPS + 2))))

    assert wrapped[0] > rail[0]


def test_milestone_chips_are_used_when_every_step_has_one() -> None:
    assert _stages(["M0 · Scope", "M1 · Design", "M2 · Build"]) == ("M0", "M1", "M2")


def test_a_single_step_without_a_milestone_disables_them_all() -> None:
    assert _stages(["M0 · Scope", "Design", "M2 · Build"]) == ()


def test_numbering_systems_are_never_mixed() -> None:
    assert _stages(["Scope", "Design"]) == ()


BRANCHES = [
    ("Purpose", ["Compliance", "Replaces Watchman"]),
    ("Capabilities", ["CI/CD", "Monitoring"]),
    ("Coverage", ["UK", "Italy"]),
]


def test_a_map_renders_as_a_png() -> None:
    output = render_mindmap("KIP", BRANCHES)
    assert output is not None
    assert output.getvalue().startswith(PNG_MAGIC)


def test_a_map_with_more_branches_is_larger() -> None:
    small = render_mindmap("KIP", BRANCHES[:2])
    large = render_mindmap("KIP", BRANCHES)
    assert small is not None and large is not None
    assert len(large.getvalue()) > len(small.getvalue())


def test_a_branch_without_items_still_renders() -> None:
    output = render_mindmap("KIP", [("Purpose", []), ("Coverage", [])])
    assert output is not None
    assert output.getvalue().startswith(PNG_MAGIC)

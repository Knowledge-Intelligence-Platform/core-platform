import pytest

from app.coverage import is_coverage_request


@pytest.mark.parametrize(
    "text",
    ["coverage", "Coverage?", "  what do you know  ", "What is covered?", "knowledge coverage"],
)
def test_a_coverage_request_is_recognised(text: str) -> None:
    assert is_coverage_request(text)


@pytest.mark.parametrize(
    "text",
    ["what do you know about KIP Service?", "how does patching work", "coverage of the estate"],
)
def test_an_ordinary_question_is_not_a_coverage_request(text: str) -> None:
    assert not is_coverage_request(text)

"""Holding messages match the question and never mention the backend."""

from __future__ import annotations

import re

import pytest

from app.waiting import (
    CATEGORIES,
    COMPARISON,
    GENERAL,
    GREETING,
    ONBOARDING,
    OWNERSHIP,
    PREREQUISITES,
    TROUBLESHOOTING,
    WORKFLOW,
    waiting_message,
)

ALL_MESSAGES = tuple(
    message
    for pool in (
        GENERAL,
        GREETING,
        ONBOARDING,
        COMPARISON,
        WORKFLOW,
        OWNERSHIP,
        TROUBLESHOOTING,
        PREREQUISITES,
    )
    for message in pool
)

FORBIDDEN = re.compile(
    r"\b(index\w*|retriev\w*|search\w*|embed\w*|vector|prompt|tool|passage|"
    r"chunk|database|model)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize(
    ("question", "pool"),
    [
        ("Hi there, I would like to know about KIP", GREETING),
        ("thanks!", GREETING),
        ("How do I onboard to KIP Service as a Service?", ONBOARDING),
        ("I am new to KIP", ONBOARDING),
        ("Compare Integration and KIP Service", COMPARISON),
        ("What is the difference between them?", COMPARISON),
        ("My deployment is failing", TROUBLESHOOTING),
        ("Where is the runbook?", TROUBLESHOOTING),
        ("What prerequisites do I need?", PREREQUISITES),
        ("Who owns operations management?", OWNERSHIP),
        ("How does KIP work end to end?", WORKFLOW),
        ("Tell me about golden images", GENERAL),
    ],
)
def test_the_message_suits_the_question(question: str, pool: tuple[str, ...]) -> None:
    assert waiting_message(question) in pool


def test_an_empty_question_still_gets_a_message() -> None:
    assert waiting_message("   ") in GENERAL


def test_no_message_mentions_backend_implementation() -> None:
    offenders = [message for message in ALL_MESSAGES if FORBIDDEN.search(message)]
    assert offenders == []


def test_every_message_is_short_enough_to_read_at_a_glance() -> None:
    assert all(0 < len(message) <= 70 for message in ALL_MESSAGES)


def test_each_category_offers_more_than_one_line() -> None:
    repeated = [pool for _, pool in CATEGORIES if len(pool) < 2]
    assert repeated == []

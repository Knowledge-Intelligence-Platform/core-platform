from typing import cast
from unittest.mock import Mock

import pytest
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.agent import PlatformKnowledgeAgent
from app.models import KnowledgeAnswer
from app.slack import FeedbackStore, SlackIntegration


def integration() -> tuple[SlackIntegration, Mock, Mock]:
    agent = Mock(spec=PlatformKnowledgeAgent)
    agent.platform_name = "Example Platform"
    agent.answer.return_value = KnowledgeAnswer(answer="Approved answer.")
    client = Mock(spec=WebClient)
    client.users_info.return_value = {
        "user": {"profile": {"email": "reader@example.com"}, "deleted": False, "is_bot": False}
    }
    client.chat_postMessage.return_value = {"ts": "2.0"}
    slack = SlackIntegration(
        bot_token="test",
        signing_secret="test",
        agent=cast(PlatformKnowledgeAgent, agent),
        maximum_message_length=3500,
        feedback_store=cast(FeedbackStore, Mock()),
        streaming_enabled=False,
        require_identity=True,
    )
    slack.client = cast(WebClient, client)
    return slack, client, agent


def test_direct_message_uses_slack_verified_email() -> None:
    slack, client, agent = integration()
    slack.process("D123", "1.0", "How does onboarding work?", requester_id="U123")
    client.users_info.assert_called_once_with(user="U123")
    agent.answer.assert_called_once_with(
        "How does onboarding work?", conversation_id="D123:1.0", user_id="reader@example.com"
    )


@pytest.mark.parametrize("channel", ["C123", "G123"])
def test_shared_channels_never_retrieve_private_content(channel: str) -> None:
    slack, client, agent = integration()
    slack.process(channel, "1.0", "How does onboarding work?", requester_id="U123")
    client.users_info.assert_not_called()
    agent.answer.assert_not_called()
    assert "direct message" in client.chat_postMessage.call_args.kwargs["text"]


@pytest.mark.parametrize(
    "user",
    [{}, {"deleted": True}, {"is_bot": True}, {"profile": {}}, {"profile": {"email": ""}}],
)
def test_missing_or_ineligible_identity_never_calls_agent(user: dict[str, object]) -> None:
    slack, client, agent = integration()
    client.users_info.return_value = {"user": user}
    slack.process("D123", "1.0", "What is the platform?", requester_id="U123")
    agent.answer.assert_not_called()


def test_slack_lookup_error_fails_closed() -> None:
    slack, client, agent = integration()
    client.users_info.side_effect = SlackApiError("missing_scope", response=Mock())
    slack.process("D123", "1.0", "What is the platform?", requester_id="U123")
    agent.answer.assert_not_called()


def test_missing_requester_fails_closed() -> None:
    slack, client, agent = integration()
    slack.process("D123", "1.0", "What is the platform?")
    client.users_info.assert_not_called()
    agent.answer.assert_not_called()

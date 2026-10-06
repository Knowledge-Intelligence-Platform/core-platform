"""Per-answer agent metrics captured through Strands lifecycle hooks.

The hooks only observe: they never modify a prompt, a model call, or a result.
Nothing here logs question text, answer text, or retrieved content.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from threading import Lock
from time import monotonic

from strands import Agent
from strands.hooks import AfterInvocationEvent, AfterModelCallEvent, BeforeInvocationEvent

LOGGER = logging.getLogger(__name__)


class AgentMetrics:
    """Times each agent invocation and reports it as a structured log record."""

    def __init__(self, *, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._lock = Lock()
        self._started: float | None = None
        self._model_calls = 0

    def register(self, agent: Agent) -> None:
        agent.add_hook(self._on_start, BeforeInvocationEvent)
        agent.add_hook(self._on_model_call, AfterModelCallEvent)
        agent.add_hook(self._on_finish, AfterInvocationEvent)

    def _on_start(self, event: BeforeInvocationEvent) -> None:
        with self._lock:
            self._started = monotonic()
            self._model_calls = 0

    def _on_model_call(self, event: AfterModelCallEvent) -> None:
        with self._lock:
            self._model_calls += 1

    def _on_finish(self, event: AfterInvocationEvent) -> None:
        with self._lock:
            started, model_calls = self._started, self._model_calls
            self._started = None
        if started is None:
            return
        usage: Mapping[str, object] = (
            event.result.metrics.accumulated_usage if event.result is not None else {}
        )
        LOGGER.info(
            "Agent invocation completed.",
            extra={
                "operation": "agent_invocation",
                "component": "agent",
                "duration_ms": round((monotonic() - started) * 1_000, 2),
                "model_calls": model_calls,
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "cache_read_input_tokens": usage.get("cacheReadInputTokens", 0),
                "cache_write_input_tokens": usage.get("cacheWriteInputTokens", 0),
                # A stable hash, never the Slack channel or user.
                "conversation": str(abs(hash(self.conversation_id)) % 10**8),
            },
        )

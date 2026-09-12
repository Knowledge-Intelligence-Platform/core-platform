"""Single source-grounded Platform Knowledge Agent."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from strands import Agent, AgentSkills, Skill
from strands.agent.conversation_manager import (
    ConversationManager,
    SlidingWindowConversationManager,
    SummarizingConversationManager,
)
from strands.models.openai_responses import OpenAIResponsesModel
from strands.session.s3_session_manager import S3SessionManager
from strands.session.session_manager import SessionManager

from app.metrics import AgentMetrics
from app.models import (
    UNMAPPED_COMPONENT_ID,
    KnowledgeAnswer,
    MindMap,
    MindMapBranch,
    SearchResult,
)
from app.search import HybridSearch

LOGGER = logging.getLogger(__name__)
INSUFFICIENT_ANSWER = "I don't have enough information to answer that reliably."

INSTRUCTIONS_PATH = Path(__file__).with_name("instructions.md")


def instructions(platform_name: str) -> str:
    """Load the agent instructions for the platform this deployment serves.

    Both placeholders are substituted rather than formatted, so a literal brace
    in the instructions cannot break loading the way an f-string once could.
    The platform is named here and nowhere else in the prompt, so a second
    tenant needs a registry, not a fork.
    """
    return (
        INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        .replace("{INSUFFICIENT_ANSWER}", INSUFFICIENT_ANSWER)
        .replace("{PLATFORM_NAME}", platform_name)
        .strip()
    )


def _presentation_skills() -> tuple[Skill, ...]:
    """Return small, instruction-only skills for supported answer formats.

    The skills deliberately contain no resources or executable tools. Every
    factual statement must still come from the retrieved passages supplied for
    the current turn.
    """
    grounding = """
Use only facts and relationships that appear in the approved passages supplied
for the current turn. Do not infer missing steps, ownership, prerequisites,
timelines, or architecture. If the passages do not support the requested view,
return the standard insufficient-information answer. Never mention this skill,
the passages, sources, retrieval, or backend implementation to the user.
""".strip()
    return (
        Skill(
            name="guided-onboarding",
            description=(
                "Present supported joining and getting-started guidance as a "
                "welcoming journey."
            ),
            instructions="\n\n".join(
                (
                    grounding,
                    """
Activate for questions about joining the platform, getting started, gaining access,
adoption, migration, prerequisites, or onboarding.

Set response_type to `onboarding`. Give a brief, natural welcome only on the
first onboarding turn in a conversation. Address the user as "you" and turn
supported actions into a short ordered journey. Start with the first supported
action, then offer one grounded next question. Be encouraging without making
guarantees or promises. When the passages establish a sequence, set 3-8 short
visual_nodes in directional order; otherwise leave visual_nodes empty.
""".strip(),
                )
            ),
            allowed_tools=[],
        ),
        Skill(
            name="service-comparison",
            description="Give a clear, grounded comparison of supported services or options.",
            instructions="\n\n".join(
                (
                    grounding,
                    """
Activate when a user compares two or more services, options, components, or
approaches. Set response_type to `comparison`. Give the shared purpose first,
then concise differences that are explicitly supported. Do not manufacture a
comparison category when one side is not described. Use a compact table only
when it improves clarity. Add visual_nodes only when the passages establish a
real relationship or sequence between the compared items.
""".strip(),
                )
            ),
            allowed_tools=[],
        ),
        Skill(
            name="workflow-visualization",
            description=(
                "Turn a supported workflow, architecture, lifecycle, or mapping "
                "into a Slack-ready high-level visual."
            ),
            instructions="\n\n".join(
                (
                    grounding,
                    """
Activate when the user asks how something works or the answer establishes a
workflow, process, lifecycle, architecture, or component mapping. Set
response_type to `mapping`. Explain the view in plain language, then set
visual_nodes to 3-8 short labels in directional order. Each node must name a
visible, supported stage or relationship. Leave visual_nodes empty if a
meaningful sequence cannot be grounded. The Slack delivery layer renders these
nodes as a diagram; do not describe rendering details to the user.
""".strip(),
                )
            ),
            allowed_tools=[],
        ),
    )

SOURCE_IDENTIFIER = re.compile(r"\s*(?:\[S\d+])+", re.IGNORECASE)
# Matches both word orders: "the provided information" and "the information
# provided". The instructions forbid these openers; this is the safety net.
BACKEND_INTRO = re.compile(
    r"^\s*(?:"
    r"(?:from|based on)\s+(?:the\s+)?(?:"
    r"(?:available|provided|retrieved)\s+(?:information|content|details)"
    r"|(?:information|content|details)\s+(?:available|provided|retrieved)"
    r")"
    r"|using\s+the\s+approved\s+.{0,40}?\s*knowledge\s+available\s+in\s+the\s+conversation"
    r")\s*[:,.-]?\s*",
    re.IGNORECASE,
)


class IntelligentBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    items: tuple[str, ...] = Field(default=(), max_length=4)


class IntelligentResponse(BaseModel):
    """Typed response used to drive the Slack knowledge experience."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    response_type: Literal["general", "onboarding", "comparison", "mapping"] = "general"
    visual_nodes: tuple[str, ...] = Field(default=(), max_length=8)
    visual_center: str = ""
    visual_branches: tuple[IntelligentBranch, ...] = Field(default=(), max_length=6)
    suggested_questions: tuple[str, ...] = Field(default=(), max_length=3)

ANSWER_FIELD = re.compile(r'"answer"\s*:\s*"')


class PartialAnswer:
    """Extracts the `answer` field from a structured-output JSON stream.

    The model streams the whole `IntelligentResponse` object, so raw deltas look
    like `{"answer":"Yo` rather than prose. This decodes just the answer field
    from whatever has arrived so far, tolerating a delta that ends mid-escape.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._start = -1

    def feed(self, delta: str) -> None:
        self._buffer += delta

    def text(self) -> str | None:
        if self._start < 0:
            match = ANSWER_FIELD.search(self._buffer)
            if match is None:
                return None
            self._start = match.end()
        raw = self._buffer[self._start :]
        decoded: list[str] = []
        index = 0
        while index < len(raw):
            character = raw[index]
            if character == "\\":
                if index + 1 >= len(raw):
                    break
                if raw[index + 1] == "u":
                    if index + 6 > len(raw):
                        break
                    decoded.append(raw[index : index + 6])
                    index += 6
                    continue
                decoded.append(raw[index : index + 2])
                index += 2
                continue
            if character == '"':
                break
            decoded.append(character)
            index += 1
        try:
            text = cast(str, json.loads(f'"{"".join(decoded)}"'))
        except ValueError:
            return None
        # An emoji is a surrogate pair that can arrive split across two deltas.
        # A lone half is not encodable as UTF-8, so hold it back until it pairs.
        if text and "\ud800" <= text[-1] <= "\udfff":
            text = text[:-1]
        return text


def public_answer(answer: str) -> str:
    """Remove internal grounding identifiers from end-user content."""
    cleaned = SOURCE_IDENTIFIER.sub("", answer).strip()
    return BACKEND_INTRO.sub("", cleaned).strip()


def _condense(text: str) -> str:
    """Normalise for comparison: straight quotes, single spaces, no end stop."""
    normalized = text.replace("\u2019", "'").replace("\u2018", "'")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.strip('"').strip().rstrip(".").casefold()


def is_refusal(answer: str) -> bool:
    """True when the answer *is* the refusal, not merely one that mentions it."""
    return _condense(answer) == _condense(INSUFFICIENT_ANSWER)


def _diagram_nodes(nodes: tuple[str, ...]) -> tuple[str, ...]:
    """Keep ordered, de-duplicated nodes, and only if they form a real sequence."""
    seen: dict[str, None] = {}
    for node in nodes:
        cleaned = re.sub(r"\s+", " ", public_answer(node)).strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    ordered = tuple(seen)
    # A one-box "flow" is not a diagram; it just looks broken in Slack.
    return ordered if len(ordered) >= 2 else ()


def _mindmap(center: str, branches: tuple[IntelligentBranch, ...]) -> MindMap | None:
    """Keep a map only when it has a subject and at least two grounded branches."""
    subject = re.sub(r"\s+", " ", public_answer(center)).strip()
    if not subject:
        return None
    kept: list[MindMapBranch] = []
    seen: set[str] = set()
    for branch in branches:
        label = re.sub(r"\s+", " ", public_answer(branch.label)).strip()
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        items: dict[str, None] = {}
        for item in branch.items:
            cleaned = re.sub(r"\s+", " ", public_answer(item)).strip()
            if cleaned and cleaned.casefold() != label.casefold():
                items.setdefault(cleaned, None)
        kept.append(MindMapBranch(label=label, items=tuple(items)[:4]))
    if len(kept) < 2:
        return None
    return MindMap(center=subject, branches=tuple(kept)[:6])


def _follow_up_questions(answer: str, questions: tuple[str, ...]) -> tuple[str, ...]:
    """Drop follow-ups the answer already states, so nothing renders twice."""
    body = _condense(answer)
    kept: dict[str, None] = {}
    for question in questions:
        cleaned = re.sub(r"\s+", " ", public_answer(question)).strip()
        if not cleaned:
            continue
        if _condense(cleaned) in body:
            continue
        kept.setdefault(cleaned, None)
    return tuple(kept)[:3]


def _session_id(conversation_id: str) -> str:
    """Slack ids contain characters that do not belong in a storage key."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", conversation_id).strip("-") or "default"


@dataclass
class Conversation:
    agent: Agent
    updated_at: datetime
    previous_question: str | None = None
    lock: Lock = field(default_factory=Lock)


class PlatformKnowledgeAgent:
    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        platform_name: str,
        search: HybridSearch,
        maximum_results: int,
        conversation_window: int = 20,
        metrics_enabled: bool = True,
        stream_interval_seconds: float = 1.0,
        summarization_enabled: bool = False,
        summary_ratio: float = 0.3,
        preserve_recent_messages: int = 10,
        session_persistence_enabled: bool = False,
        session_bucket: str | None = None,
        session_prefix: str = "sessions/slack",
        aws_region: str | None = None,
    ) -> None:
        self.search = search
        self.platform_name = platform_name
        self.instructions = instructions(platform_name)
        self.maximum_results = maximum_results
        self.conversation_window = conversation_window
        self.metrics_enabled = metrics_enabled
        self.stream_interval_seconds = stream_interval_seconds
        self.summarization_enabled = summarization_enabled
        self.summary_ratio = summary_ratio
        self.preserve_recent_messages = preserve_recent_messages
        self.session_persistence_enabled = session_persistence_enabled
        self.session_bucket = session_bucket
        self.session_prefix = session_prefix
        self.aws_region = aws_region
        self.model = OpenAIResponsesModel(
            model_id=model_id,
            client_args={"api_key": api_key},
        )
        self._conversations: dict[str, Conversation] = {}
        self._conversations_lock = Lock()
        self._conversation_retention = timedelta(hours=2)

    def answer(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
    ) -> KnowledgeAnswer:
        conversation = self._for(conversation_id)
        with conversation.lock:
            prompt = self._prepare(conversation, question)
            if prompt is None:
                return KnowledgeAnswer(answer=INSUFFICIENT_ANSWER)
            result = conversation.agent(
                prompt,
                structured_output_model=IntelligentResponse,
            )
            structured = cast(IntelligentResponse | None, result.structured_output)
            response = structured or IntelligentResponse(answer=str(result).strip())
            return self._knowledge_answer(response)

    def answer_stream(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        on_partial: Callable[[str], None] | None = None,
    ) -> KnowledgeAnswer:
        """Answer while reporting the answer text as it is generated.

        `on_partial` is called at most once per `stream_interval_seconds` with the
        answer so far, so a delivery channel can update a message progressively.
        """
        conversation = self._for(conversation_id)
        with conversation.lock:
            prompt = self._prepare(conversation, question)
            if prompt is None:
                return KnowledgeAnswer(answer=INSUFFICIENT_ANSWER)
            return asyncio.run(self._stream(conversation, prompt, on_partial))

    async def _stream(
        self,
        conversation: Conversation,
        prompt: str,
        on_partial: Callable[[str], None] | None,
    ) -> KnowledgeAnswer:
        partial = PartialAnswer()
        structured: IntelligentResponse | None = None
        emitted_at = 0.0
        emitted = ""
        async for event in conversation.agent.stream_async(
            prompt,
            structured_output_model=IntelligentResponse,
        ):
            if not isinstance(event, dict):
                continue
            output = event.get("structured_output")
            if isinstance(output, IntelligentResponse):
                structured = output
            delta = event.get("data")
            if not isinstance(delta, str) or not delta:
                continue
            partial.feed(delta)
            if on_partial is None:
                continue
            now = monotonic()
            if now - emitted_at < self.stream_interval_seconds:
                continue
            text = partial.text()
            if text and text != emitted:
                emitted, emitted_at = text, now
                on_partial(text)
        if structured is None:
            text = (partial.text() or "").strip()
            structured = IntelligentResponse(answer=text or INSUFFICIENT_ANSWER)
        return self._knowledge_answer(structured)

    def _prepare(self, conversation: Conversation, question: str) -> str | None:
        """Retrieve for this turn and build the grounded prompt, or None if empty."""
        normalized_question = question.strip()
        retrieval_query = self._retrieval_query(
            normalized_question,
            conversation.previous_question,
        )
        results = self.search.search(retrieval_query, self.maximum_results)
        conversation.previous_question = normalized_question
        conversation.updated_at = datetime.now(UTC)
        if not results:
            LOGGER.info(
                "Retrieval returned nothing; refusing before the model call.",
                extra={
                    "operation": "retrieval_empty",
                    "component": "agent",
                    "expanded_query": retrieval_query != normalized_question,
                },
            )
            return None
        return self._grounded_prompt(normalized_question, results)

    def _for(self, conversation_id: str | None) -> Conversation:
        if conversation_id:
            return self._conversation(conversation_id)
        return self._new_conversation(f"ephemeral:{uuid4()}", persist=False)

    def _new_conversation(
        self, conversation_id: str, *, persist: bool = True
    ) -> Conversation:
        return Conversation(
            agent=self._build_agent(conversation_id, persist=persist),
            updated_at=datetime.now(UTC),
        )

    def _conversation(self, conversation_id: str) -> Conversation:
        now = datetime.now(UTC)
        with self._conversations_lock:
            self._conversations = {
                key: value
                for key, value in self._conversations.items()
                if now - value.updated_at <= self._conversation_retention
            }
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                conversation = self._new_conversation(conversation_id)
                self._conversations[conversation_id] = conversation
            return conversation

    def _build_agent(self, conversation_id: str, *, persist: bool = True) -> Agent:
        agent = Agent(
            model=self.model,
            system_prompt=self.instructions,
            plugins=[AgentSkills(skills=list(_presentation_skills()), strict=True)],
            conversation_manager=self._conversation_manager(),
            session_manager=self._session_manager(conversation_id) if persist else None,
        )
        if self.metrics_enabled:
            AgentMetrics(conversation_id=conversation_id).register(agent)
        return agent

    def _conversation_manager(self) -> ConversationManager:
        if self.summarization_enabled:
            return SummarizingConversationManager(
                summary_ratio=self.summary_ratio,
                preserve_recent_messages=self.preserve_recent_messages,
            )
        return SlidingWindowConversationManager(
            window_size=self.conversation_window,
            should_truncate_results=True,
            per_turn=True,
        )

    def _session_manager(self, conversation_id: str) -> SessionManager | None:
        if not self.session_persistence_enabled or not self.session_bucket:
            return None
        # S3SessionManager reads the stored session during construction, so this
        # touches S3 on the request path. Losing durable history must never cost
        # the user their answer: fall back to an in-memory conversation instead.
        try:
            return S3SessionManager(
                session_id=_session_id(conversation_id),
                bucket=self.session_bucket,
                prefix=self.session_prefix,
                region_name=self.aws_region,
            )
        except Exception:
            LOGGER.exception(
                "Conversation persistence unavailable; continuing without it.",
                extra={"operation": "session_manager", "component": "agent"},
            )
            return None

    @staticmethod
    def _retrieval_query(question: str, previous_question: str | None) -> str:
        normalized = question.strip()
        terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", normalized)
        if len(terms) <= 4:
            normalized = "\n".join(
                (
                    normalized,
                    "Find the relevant service overview, architecture, workflow, "
                    "prerequisites, and onboarding guidance.",
                )
            )
        if previous_question is None:
            return normalized
        return (
            f"{normalized}\nPrevious question in this conversation: {previous_question}"
        )

    @staticmethod
    def _grounded_prompt(
        question: str,
        results: tuple[SearchResult, ...],
    ) -> str:
        passages = [
            {
                "source_id": result.source_id,
                "title": result.chunk.title,
                "location": result.citation,
                **(
                    {}
                    if result.chunk.component_id == UNMAPPED_COMPONENT_ID
                    else {"component_id": result.chunk.component_id}
                ),
                "text": result.chunk.text,
            }
            for result in results
        ]
        return "\n".join(
            (
                f"Current question: {question}",
                "Approved passages:",
                json.dumps(passages, ensure_ascii=False, separators=(",", ":")),
            )
        )

    @staticmethod
    def _knowledge_answer(response: IntelligentResponse) -> KnowledgeAnswer:
        """Normalise the model's structured output into what the channel renders.

        The prompt asks for these rules; this enforces them, so a model that
        drifts cannot put follow-up buttons or a flow diagram under a refusal,
        or restate content the delivery channel already renders separately.
        """
        answer = response.answer.strip()
        if not answer or is_refusal(answer):
            return KnowledgeAnswer(answer=INSUFFICIENT_ANSWER)
        nodes = _diagram_nodes(response.visual_nodes)
        mindmap = (
            None if nodes else _mindmap(response.visual_center, response.visual_branches)
        )
        return KnowledgeAnswer(
            answer=answer,
            visual="\n↓\n".join(nodes) if nodes else None,
            mindmap=mindmap,
            suggested_questions=_follow_up_questions(answer, response.suggested_questions),
            response_type=response.response_type,
        )

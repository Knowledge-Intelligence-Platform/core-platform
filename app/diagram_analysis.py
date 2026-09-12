"""Grounded diagram understanding for candidate PDF pages."""

from __future__ import annotations

import logging

import fitz  # type: ignore[import-untyped]
from strands import Agent
from strands.models.openai_responses import OpenAIResponsesModel
from strands.types.content import ContentBlock as StrandsContentBlock

from app.models import ContentBlock

LOGGER = logging.getLogger(__name__)
NO_DIAGRAM = "NO_DIAGRAM"
DIAGRAM_TERMS = (
    "architecture",
    "diagram",
    "flow",
    "workflow",
    "process",
    "sequence",
    "mapping",
    "lifecycle",
    "overview",
)
INSTRUCTIONS = """
You analyze diagrams in approved PDF pages.

Describe only relationships visibly established by the supplied page image.
Capture the diagram title, major nodes, directional connections, boundaries,
groups, legends, and important labels. Preserve the direction of arrows.
Do not infer missing steps, implementation details, ownership, or live state.
Use accompanying extracted text only to clarify visible labels.

Return a concise textual description suitable for knowledge retrieval. Start
with "Visual description:". If the page has no meaningful workflow, process,
architecture, lifecycle, chart, or mapping diagram, return exactly NO_DIAGRAM.
""".strip()


class DiagramAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        render_dpi: int,
        maximum_pages: int,
    ) -> None:
        self.model = OpenAIResponsesModel(
            model_id=model_id,
            client_args={"api_key": api_key},
        )
        self.render_scale = render_dpi / 72
        self.maximum_pages = maximum_pages

    def analyze(self, content: bytes, source_location: str) -> tuple[ContentBlock, ...]:
        document = fitz.open(stream=content, filetype="pdf")
        blocks: list[ContentBlock] = []
        analyzed = 0
        try:
            for page_number, page in enumerate(document, start=1):
                if analyzed >= self.maximum_pages:
                    break
                text = page.get_text("text").strip()
                if not self._is_candidate(page, text):
                    continue
                analyzed += 1
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(self.render_scale, self.render_scale),
                    alpha=False,
                )
                description = self._describe(pixmap.tobytes("png"), text)
                if description:
                    blocks.append(
                        ContentBlock(
                            text=description,
                            page_number=page_number,
                            heading_path=("Visual content",),
                            visual_description=True,
                        )
                    )
        except Exception:
            LOGGER.exception(
                "PDF diagram analysis failed.",
                extra={
                    "operation": "analyze_diagrams",
                    "component": "ingestion",
                    "source_location": source_location,
                },
            )
        finally:
            document.close()
        return tuple(blocks)

    @staticmethod
    def _is_candidate(page: fitz.Page, text: str) -> bool:
        normalized = text.casefold()
        has_visual_term = any(term in normalized for term in DIAGRAM_TERMS)
        return (
            bool(page.get_images(full=True))
            or len(page.get_drawings()) >= 4
            or has_visual_term
        )

    def _describe(self, image: bytes, extracted_text: str) -> str | None:
        context = extracted_text[:4_000]
        agent = Agent(model=self.model, system_prompt=INSTRUCTIONS)
        prompt: list[StrandsContentBlock] = [
            {
                "text": (
                    "Analyze this PDF page for a meaningful diagram. "
                    f"Extracted page text follows:\n{context}"
                )
            },
            {
                "image": {
                    "format": "png",
                    "source": {"bytes": image},
                }
            },
        ]
        result = str(agent(prompt)).strip()
        if result == NO_DIAGRAM or result.startswith(NO_DIAGRAM):
            return None
        return result

"""Flow rendering for Slack.

Short flows are drawn directly: the rail renderer keeps the picture landscape
at every step count and carries a second line per card, which Graphviz cannot.
Beyond `RAIL_MAX_STEPS` a single column grows taller than Slack will show at a
readable size, so Graphviz takes over and wraps the steps into two columns. It
also stands in if the rail renderer fails, and the rail stands in when the
`dot` binary is missing, so neither a system package nor a layout quirk loses
the picture.

Every label is drawn as given: nothing here adds, merges, or infers a step. The
only interpretation is cosmetic — a leading stage token such as `M0` is lifted
into its own chip so the label beside it reads cleanly.
"""

from __future__ import annotations

import html
import logging
import re
import textwrap
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from subprocess import CalledProcessError

import graphviz
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LOGGER = logging.getLogger(__name__)

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont
Color = tuple[int, int, int]

MAXIMUM_STEPS = 8
RAIL_MAX_STEPS = 6
DEFAULT_FLOW_TITLE = "High-level view"
WIDTH = 1500
MARGIN = 64
RAIL_X = 152
CARD_LEFT = 232
BADGE_RADIUS = 30
CARD_PADDING = 34
ACCENT_WIDTH = 6
STEP_GAP = 30
MINIMUM_CARD_HEIGHT = 108
CORNER = 22

BACKGROUND_TOP = (11, 15, 21)
BACKGROUND_BOTTOM = (23, 28, 37)
GRID = (255, 255, 255, 6)
CARD_TOP = (32, 38, 48)
CARD_BOTTOM = (25, 30, 39)
CARD_EDGE = (58, 66, 78)
TITLE_COLOR = (246, 247, 249)
SUBTITLE_COLOR = (139, 150, 164)
LABEL_COLOR = (237, 241, 246)
DETAIL_COLOR = (150, 161, 175)
RAIL_COLOR = (52, 60, 72)
BADGE_TEXT = (12, 16, 22)

PALETTE: tuple[Color, ...] = (
    (56, 189, 248),
    (167, 139, 250),
    (52, 211, 153),
    (251, 191, 36),
    (96, 165, 250),
    (244, 114, 182),
    (45, 212, 191),
    (248, 113, 113),
)

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans{suffix}.ttf",
    "/System/Library/Fonts/Supplemental/Arial{mac}.ttf",
)
SEPARATORS = ("➜", "→", "->")
STAGE_TOKEN = re.compile(
    r"^\s*((?:[A-Z]\d{1,2})|(?:(?:Step|Phase|Stage|Milestone)\s+\d{1,2})|(?:\d{1,2}\.))"
    r"\s*[·:\-–—]\s*(.+)$",
    re.IGNORECASE,
)


def _font(size: int, *, bold: bool = False) -> Font:
    for template in FONT_CANDIDATES:
        candidate = Path(
            template.format(suffix="-Bold" if bold else "", mac=" Bold" if bold else "")
        )
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _wrap(text: str, font: Font, maximum_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > maximum_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _split_step(step: str) -> tuple[str, str]:
    """Separate a node's headline from any inline detail it carries."""
    normalized = step
    for separator in SEPARATORS:
        normalized = normalized.replace(separator, "\x1f")
    parts = [part.strip() for part in normalized.split("\x1f") if part.strip()]
    if not parts:
        return step.strip(), ""
    return parts[0], "  ➜  ".join(parts[1:])


def _split_stage(headline: str) -> tuple[str, str]:
    """Lift a leading stage token such as `M0` out of the label."""
    match = STAGE_TOKEN.match(headline)
    if match is None:
        return "", headline
    return match.group(1).upper(), match.group(2).strip()


def _mix(start: Color, end: Color, ratio: float) -> Color:
    return (
        round(start[0] + (end[0] - start[0]) * ratio),
        round(start[1] + (end[1] - start[1]) * ratio),
        round(start[2] + (end[2] - start[2]) * ratio),
    )


def _tint(color: Color, ratio: float) -> Color:
    """Blend an accent toward the card surface for chips and washes."""
    return _mix(CARD_TOP, color, ratio)


def _canvas(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), BACKGROUND_TOP)
    draw = ImageDraw.Draw(image)
    for row in range(height):
        draw.line(
            ((0, row), (width, row)),
            fill=_mix(BACKGROUND_TOP, BACKGROUND_BOTTOM, row / max(1, height - 1)),
        )
    grid = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for x in range(0, width, 48):
        grid_draw.line(((x, 0), (x, height)), fill=GRID, width=1)
    for y in range(0, height, 48):
        grid_draw.line(((0, y), (width, y)), fill=GRID, width=1)
    image = Image.alpha_composite(image.convert("RGBA"), grid)
    return image.convert("RGB")

GRAPHVIZ_FONT = "Helvetica"
GRAPHVIZ_BACKGROUND = "#0f141b"
GRAPHVIZ_CARD = "#20262f"
GRAPHVIZ_EDGE_COLOR = "#39414e"
GRAPHVIZ_LABEL = "#eef2f7"
GRAPHVIZ_MUTED = "#94a1b2"
WRAP_COLUMNS = 44
CARD_COLUMNS = 430
WRAP_AFTER = 5


def _hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _html_lines(text: str, *, columns: int = WRAP_COLUMNS) -> list[str]:
    """Wrap to a fixed column count: Graphviz HTML labels never wrap themselves."""
    return textwrap.wrap(text, width=columns) or [""]


def _stages(labels: list[str]) -> tuple[str, ...]:
    """Stage tokens, only when every step carries one."""
    found = tuple(_split_stage(_split_step(step)[0])[0] for step in labels)
    return found if all(found) else ()


def _node_label(index: int, step: str, accent: Color, chip: str) -> str:
    """One card, as a Graphviz HTML label.

    The accent is carried by the border and the chip rather than a coloured edge
    cell: a cell at the table edge is not clipped by ROUNDED, so it bleeds past
    the corner. Every card declares the same WIDTH so the column stays flush.
    """
    headline, detail = _split_step(step)
    if chip and chip != f"{index + 1:02d}":
        headline = _split_stage(headline)[1]
    headline_html = '<BR ALIGN="LEFT"/>'.join(
        html.escape(line) for line in _html_lines(headline)
    )
    rows = [
        '<TR><TD ALIGN="LEFT">'
        f'<FONT COLOR="{_hex(accent)}" POINT-SIZE="12"><B>{html.escape(chip)}</B></FONT>'
        "</TD></TR>",
        '<TR><TD ALIGN="LEFT" BALIGN="LEFT">'
        f'<FONT COLOR="{GRAPHVIZ_LABEL}" POINT-SIZE="17"><B>{headline_html}</B></FONT>'
        "</TD></TR>",
    ]
    if detail:
        detail_html = '<BR ALIGN="LEFT"/>'.join(
            html.escape(line) for line in _html_lines(detail, columns=52)
        )
        rows.append(
            '<TR><TD ALIGN="LEFT" BALIGN="LEFT">'
            f'<FONT COLOR="{GRAPHVIZ_MUTED}" POINT-SIZE="12">{detail_html}</FONT>'
            "</TD></TR>"
        )
    return (
        '<<TABLE STYLE="ROUNDED" BORDER="2" CELLBORDER="0" CELLSPACING="0" '
        f'CELLPADDING="11" WIDTH="{CARD_COLUMNS}" COLOR="{_hex(accent)}" '
        f'BGCOLOR="{GRAPHVIZ_CARD}">' + "".join(rows) + "</TABLE>>"
    )


def _render_with_graphviz(labels: list[str], title: str) -> BytesIO:
    """Lay the flow out with Graphviz and rasterise it.

    A long flow is wrapped into two columns. A single tall column is what
    Graphviz produces by default, and Slack scales a tall image down until the
    labels stop being readable; two columns keep the picture close to landscape.
    """
    columns = 2 if len(labels) >= WRAP_AFTER else 1
    graph = graphviz.Digraph("flow", format="png")
    graph.attr(
        bgcolor=GRAPHVIZ_BACKGROUND,
        rankdir="TB",
        pad="0.4",
        nodesep="0.45",
        ranksep="0.40",
        dpi="150",
        label=f"{title}\n\n",
        labelloc="t",
        labeljust="l",
        fontname=GRAPHVIZ_FONT,
        fontsize="22",
        fontcolor=GRAPHVIZ_LABEL,
        splines="ortho",
    )
    graph.attr("node", shape="plaintext", margin="0", fontname=GRAPHVIZ_FONT)
    graph.attr("edge", penwidth="2.2", arrowsize="0.8")

    stages = _stages(labels)
    for index, step in enumerate(labels):
        chip = stages[index] if stages else f"{index + 1:02d}"
        graph.node(
            f"n{index}", _node_label(index, step, PALETTE[index % len(PALETTE)], chip)
        )

    if columns > 1:
        for start in range(0, len(labels), columns):
            with graph.subgraph() as row:
                row.attr(rank="same")
                for index in range(start, min(start + columns, len(labels))):
                    row.node(f"n{index}")
        for index in range(len(labels) - columns):
            graph.edge(f"n{index}", f"n{index + columns}", style="invis", weight="12")

    for index in range(len(labels) - 1):
        same_row = columns > 1 and index // columns == (index + 1) // columns
        graph.edge(
            f"n{index}",
            f"n{index + 1}",
            color=_hex(_mix(CARD_EDGE, PALETTE[index % len(PALETTE)], 0.55)),
            constraint="false" if same_row else "true",
        )
    return BytesIO(graph.pipe(format="png"))


def _map_node(text: str, colour: str, *, size: int, bold: bool, fill: str, columns: int) -> str:
    lines = '<BR ALIGN="CENTER"/>'.join(
        html.escape(line) for line in _html_lines(text, columns=columns)
    )
    body = f"<B>{lines}</B>" if bold else lines
    return (
        '<<TABLE STYLE="ROUNDED" BORDER="2" CELLBORDER="0" CELLSPACING="0" '
        f'CELLPADDING="10" COLOR="{colour}" BGCOLOR="{fill}"><TR><TD>'
        f'<FONT COLOR="{GRAPHVIZ_LABEL}" POINT-SIZE="{size}">{body}</FONT>'
        "</TD></TR></TABLE>>"
    )


def render_mindmap(
    center: str,
    branches: Sequence[tuple[str, Sequence[str]]],
    *,
    title: str = "Knowledge map",
) -> BytesIO | None:
    """Render a radial map of a subject and its areas, or None without Graphviz."""
    graph = graphviz.Graph("mindmap", engine="twopi", format="png")
    graph.attr(
        bgcolor=GRAPHVIZ_BACKGROUND,
        overlap="false",
        splines="curved",
        ranksep="2.4 equally",
        dpi="150",
        root="center",
        pad="0.4",
        label=f"{title}\n\n",
        labelloc="t",
        labeljust="l",
        fontname=GRAPHVIZ_FONT,
        fontsize="22",
        fontcolor=GRAPHVIZ_LABEL,
    )
    graph.attr("node", shape="plaintext", margin="0", fontname=GRAPHVIZ_FONT)
    graph.node(
        "center",
        _map_node(center, "#f8fafc", size=25, bold=True, fill="#1c2531", columns=18),
    )
    for index, (label, items) in enumerate(branches):
        accent = _hex(PALETTE[index % len(PALETTE)])
        branch_id = f"b{index}"
        graph.node(
            branch_id,
            _map_node(label, accent, size=17, bold=True, fill=GRAPHVIZ_CARD, columns=22),
        )
        graph.edge("center", branch_id, color=accent, penwidth="5")
        for item_index, item in enumerate(items):
            leaf_id = f"{branch_id}_{item_index}"
            graph.node(
                leaf_id,
                _map_node(item, accent, size=13, bold=False, fill="#181e26", columns=26),
            )
            graph.edge(branch_id, leaf_id, color=accent, penwidth="2.4")
    try:
        return BytesIO(graph.pipe(format="png"))
    except (graphviz.ExecutableNotFound, CalledProcessError, OSError):
        LOGGER.warning(
            "Graphviz unavailable; the knowledge map cannot be rendered.",
            extra={"operation": "render_mindmap", "component": "diagram"},
        )
        return None


def render_flow(steps: Sequence[str], *, title: str = DEFAULT_FLOW_TITLE) -> BytesIO:
    """Render the grounded steps with whichever renderer suits their number."""
    labels = [step.strip() for step in steps if step.strip()][:MAXIMUM_STEPS]
    if len(labels) <= RAIL_MAX_STEPS:
        try:
            return _render_with_pillow(labels, title)
        except OSError:
            LOGGER.warning(
                "Rail renderer failed; laying the flow out with Graphviz.",
                extra={"operation": "render_flow", "component": "diagram"},
            )
    try:
        return _render_with_graphviz(labels, title)
    except (graphviz.ExecutableNotFound, CalledProcessError, OSError):
        LOGGER.warning(
            "Graphviz unavailable; rendering the flow with the rail renderer.",
            extra={"operation": "render_flow", "component": "diagram"},
        )
        return _render_with_pillow(labels, title)


def _render_with_pillow(labels: list[str], title: str) -> BytesIO:
    """Draw the flow as a numbered rail, one card per step."""
    title_font = _font(42, bold=True)
    subtitle_font = _font(23)
    label_font = _font(31, bold=True)
    detail_font = _font(24)
    badge_font = _font(25, bold=True)
    chip_font = _font(21, bold=True)

    text_width = WIDTH - MARGIN - CARD_LEFT - CARD_PADDING * 2
    label_height = 42
    detail_height = 34
    chip_height = 38

    layout: list[tuple[str, list[str], list[str], int]] = []
    for step in labels:
        headline, detail = _split_step(step)
        stage, headline = _split_stage(headline)
        headline_lines = _wrap(headline, label_font, text_width)
        detail_lines = _wrap(detail, detail_font, text_width) if detail else []
        height = CARD_PADDING * 2 + len(headline_lines) * label_height
        if stage:
            height += chip_height
        if detail_lines:
            height += 8 + len(detail_lines) * detail_height
        layout.append(
            (stage, headline_lines, detail_lines, max(height, MINIMUM_CARD_HEIGHT))
        )

    header_height = 156
    body_height = sum(item[3] for item in layout) + STEP_GAP * max(0, len(layout) - 1)
    height = header_height + body_height + 48

    image = _canvas(WIDTH, height)

    shadow = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    top = header_height
    positions: list[tuple[int, int, int]] = []
    for _, _, _, card_height in layout:
        bottom = top + card_height
        shadow_draw.rounded_rectangle(
            (CARD_LEFT + 2, top + 10, WIDTH - MARGIN + 2, bottom + 10),
            CORNER,
            fill=(0, 0, 0, 132),
        )
        positions.append((top, bottom, top + card_height // 2))
        top = bottom + STEP_GAP
    image = Image.alpha_composite(
        image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(11))
    ).convert("RGB")
    draw = ImageDraw.Draw(image)

    draw.text((MARGIN, 50), title[:64], fill=TITLE_COLOR, font=title_font)
    draw.text(
        (MARGIN, 106),
        f"{len(layout)} steps" if len(layout) != 1 else "1 step",
        fill=SUBTITLE_COLOR,
        font=subtitle_font,
    )
    for offset in range(220):
        draw.line(
            ((MARGIN + offset, header_height - 24), (MARGIN + offset, header_height - 21)),
            fill=_mix(PALETTE[0], PALETTE[1], offset / 219),
        )

    if positions:
        rail_top, rail_bottom = positions[0][2], positions[-1][2]
        for y in range(rail_top, rail_bottom):
            span = max(1, rail_bottom - rail_top)
            slot = (y - rail_top) / span * max(1, len(positions) - 1)
            first = min(int(slot), len(positions) - 1)
            second = min(first + 1, len(positions) - 1)
            colour = _mix(
                _mix(RAIL_COLOR, PALETTE[first % len(PALETTE)], 0.55),
                _mix(RAIL_COLOR, PALETTE[second % len(PALETTE)], 0.55),
                slot - first,
            )
            draw.line(((RAIL_X - 2, y), (RAIL_X + 1, y)), fill=colour)

    for index, (stage, headline_lines, detail_lines, _) in enumerate(layout):
        accent = PALETTE[index % len(PALETTE)]
        card_top, card_bottom, centre = positions[index]
        right = WIDTH - MARGIN

        panel = Image.new("RGB", (right - CARD_LEFT, card_bottom - card_top), CARD_TOP)
        panel_draw = ImageDraw.Draw(panel)
        for row in range(panel.height):
            panel_draw.line(
                ((0, row), (panel.width, row)),
                fill=_mix(CARD_TOP, CARD_BOTTOM, row / max(1, panel.height - 1)),
            )
        mask = Image.new("L", panel.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, panel.width - 1, panel.height - 1), CORNER, fill=255
        )
        image.paste(panel, (CARD_LEFT, card_top), mask)
        draw.rounded_rectangle(
            (CARD_LEFT, card_top, right, card_bottom),
            CORNER,
            outline=CARD_EDGE,
            width=2,
        )
        draw.rounded_rectangle(
            (CARD_LEFT, card_top + 18, CARD_LEFT + ACCENT_WIDTH * 2, card_bottom - 18),
            ACCENT_WIDTH,
            fill=accent,
        )

        text_left = CARD_LEFT + CARD_PADDING * 2
        text_top = card_top + CARD_PADDING
        if stage:
            chip_width = int(chip_font.getlength(stage)) + 30
            draw.rounded_rectangle(
                (text_left, text_top - 4, text_left + chip_width, text_top + 24),
                13,
                fill=_tint(accent, 0.22),
                outline=_tint(accent, 0.55),
                width=1,
            )
            draw.text(
                (text_left + chip_width // 2, text_top + 11),
                stage,
                fill=_mix(accent, (255, 255, 255), 0.35),
                font=chip_font,
                anchor="mm",
            )
            text_top += chip_height
        for line in headline_lines:
            draw.text((text_left, text_top), line, fill=LABEL_COLOR, font=label_font)
            text_top += label_height
        if detail_lines:
            text_top += 8
            for line in detail_lines:
                draw.text((text_left, text_top), line, fill=DETAIL_COLOR, font=detail_font)
                text_top += detail_height

        draw.ellipse(
            (
                RAIL_X - BADGE_RADIUS - 7,
                centre - BADGE_RADIUS - 7,
                RAIL_X + BADGE_RADIUS + 7,
                centre + BADGE_RADIUS + 7,
            ),
            fill=_mix(BACKGROUND_BOTTOM, accent, 0.18),
        )
        draw.ellipse(
            (
                RAIL_X - BADGE_RADIUS,
                centre - BADGE_RADIUS,
                RAIL_X + BADGE_RADIUS,
                centre + BADGE_RADIUS,
            ),
            fill=accent,
        )
        draw.text(
            (RAIL_X, centre + 1),
            f"{index + 1:02d}",
            fill=BADGE_TEXT,
            font=badge_font,
            anchor="mm",
        )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output

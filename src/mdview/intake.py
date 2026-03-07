"""Content intake helpers that normalize sources into the mdview DOM."""

import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from mdview.dom import Block, ConstraintProfile, Document, Line, StyleProfile

BLOCK_TYPES: Tuple[str, ...] = (
    "prose",
    "table_like",
    "list_like",
    "code_like",
    "heading_like",
    "delimiter_like",
)
_ORDERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s+")
_BULLET_LIST_RE = re.compile(r"^\s*[-*+]\s+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_DELIMITER_RE = re.compile(r"^\s*([-=_*])\1{2,}\s*$")
_WIDE_CHARS = {"W", "F"}


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if char == "\t":
            width += 4
            continue
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in _WIDE_CHARS else 1
    return width


def _box_char_count(text: str) -> int:
    count = 0
    for char in text:
        codepoint = ord(char)
        if 0x2500 <= codepoint <= 0x257F:
            count += 1
    return count


def _line_feature_vector(text: str) -> Dict[str, float]:
    stripped = text.strip()
    char_count = float(len(text))
    display_width = float(_display_width(text))
    letter_or_digit = sum(1 for char in text if char.isalnum())
    spaces = sum(1 for char in text if char.isspace())
    delimiters = sum(
        1 for char in text if char in "|-_=+*/:\\[]{}()<>#`~.,;!?"
    )
    box_chars = _box_char_count(text)
    prose_ratio = (letter_or_digit + spaces) / char_count if char_count else 0.0
    delimiter_ratio = delimiters / char_count if char_count else 0.0
    table_pipe_count = text.count("|")
    repeated_spacing = bool(re.search(r"\S {2,}\S", text))
    is_empty = not stripped
    is_separator = bool(_DELIMITER_RE.match(text))
    bullet_marker = bool(_BULLET_LIST_RE.match(text))
    ordered_marker = bool(_ORDERED_LIST_RE.match(text))
    heading_marker = bool(_HEADING_RE.match(text))
    code_fence = bool(_FENCE_RE.match(text))
    leading_spaces = len(text) - len(text.lstrip(" "))

    return {
        "char_count": char_count,
        "display_width": display_width,
        "prose_ratio": prose_ratio,
        "delimiter_ratio": delimiter_ratio,
        "box_char_count": float(box_chars),
        "table_pipe_count": float(table_pipe_count),
        "repeated_spacing": 1.0 if repeated_spacing else 0.0,
        "is_empty": 1.0 if is_empty else 0.0,
        "is_separator": 1.0 if is_separator else 0.0,
        "bullet_marker": 1.0 if bullet_marker else 0.0,
        "ordered_marker": 1.0 if ordered_marker else 0.0,
        "heading_marker": 1.0 if heading_marker else 0.0,
        "code_fence": 1.0 if code_fence else 0.0,
        "leading_spaces": float(leading_spaces),
    }


def _average(lines: Sequence[Line], key: str) -> float:
    if not lines:
        return 0.0
    return sum(line.feature_vector.get(key, 0.0) for line in lines) / len(lines)


def _line_ratio(lines: Sequence[Line], key: str) -> float:
    if not lines:
        return 0.0
    positive = sum(1 for line in lines if line.feature_vector.get(key, 0.0) > 0.0)
    return positive / len(lines)


def _normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
    clamped = {key: max(value, 0.0) for key, value in scores.items()}
    total = sum(clamped.values())
    if total <= 0.0:
        equal = 1.0 / len(BLOCK_TYPES)
        return {block_type: equal for block_type in BLOCK_TYPES}
    return {key: value / total for key, value in clamped.items()}


def _initial_block_scores(lines: Sequence[Line]) -> Dict[str, float]:
    prose_ratio = _average(lines, "prose_ratio")
    delimiter_ratio = _average(lines, "delimiter_ratio")
    table_pipe_ratio = _line_ratio(lines, "table_pipe_count")
    repeated_spacing_ratio = _line_ratio(lines, "repeated_spacing")
    list_ratio = _line_ratio(lines, "bullet_marker") + _line_ratio(lines, "ordered_marker")
    heading_ratio = _line_ratio(lines, "heading_marker")
    separator_ratio = _line_ratio(lines, "is_separator")
    fence_ratio = _line_ratio(lines, "code_fence")
    box_char_avg = _average(lines, "box_char_count")
    indent_avg = _average(lines, "leading_spaces")

    scores = {
        "prose": 0.25 + (0.9 * prose_ratio) - (0.4 * delimiter_ratio),
        "table_like": (0.7 * table_pipe_ratio)
        + (0.6 * repeated_spacing_ratio)
        + min(box_char_avg / 4.0, 0.5),
        "list_like": 0.2 + (0.9 * min(list_ratio, 1.0)),
        "code_like": (0.7 * fence_ratio)
        + (0.5 * delimiter_ratio)
        + (0.2 if indent_avg >= 4.0 else 0.0),
        "heading_like": 0.1 + (1.2 * heading_ratio),
        "delimiter_like": 0.2 + (1.1 * separator_ratio),
    }
    return _normalize_scores(scores)


def _segment_blocks(lines: Sequence[Line]) -> List[Tuple[Line, ...]]:
    blocks: List[Tuple[Line, ...]] = []
    current: List[Line] = []
    in_fence = False

    for line in lines:
        features = line.feature_vector
        is_empty = features.get("is_empty", 0.0) > 0.0
        is_fence = features.get("code_fence", 0.0) > 0.0
        is_separator = features.get("is_separator", 0.0) > 0.0

        if is_fence and current:
            if in_fence:
                current.append(line)
                blocks.append(tuple(current))
                current = []
                in_fence = False
                continue
            blocks.append(tuple(current))
            current = [line]
            in_fence = True
            continue
        if is_fence and not current:
            current = [line]
            in_fence = True
            continue

        if in_fence:
            current.append(line)
            continue

        if is_empty:
            if current:
                blocks.append(tuple(current))
                current = []
            continue

        if is_separator and current:
            blocks.append(tuple(current))
            blocks.append((line,))
            current = []
            continue

        current.append(line)

    if current:
        blocks.append(tuple(current))

    return blocks


def _top_type(scores: Dict[str, float]) -> str:
    return max(BLOCK_TYPES, key=lambda block_type: (scores[block_type], block_type))


def _build_constraints(scores: Dict[str, float]) -> ConstraintProfile:
    top_type = _top_type(scores)
    no_reflow = top_type in {"table_like", "code_like", "delimiter_like"}
    minimum_width = 78 if top_type == "table_like" else 0
    preserve_indentation = top_type in {"code_like", "list_like"}
    wrap_hint = "none" if no_reflow else ("prose" if top_type == "prose" else "auto")
    return ConstraintProfile(
        no_reflow=no_reflow,
        minimum_width=minimum_width,
        preserve_indentation=preserve_indentation,
        wrap_hint=wrap_hint,
    )


def _pass1_lines(raw_lines: Iterable[str]) -> Tuple[Line, ...]:
    analyzed: List[Line] = []
    for text in raw_lines:
        features = _line_feature_vector(text)
        analyzed.append(
            Line.from_source(
                text,
                display_width=int(features["display_width"]),
                feature_vector=features,
            )
        )
    return tuple(analyzed)


def _pass2_blocks(lines: Sequence[Line]) -> Tuple[Block, ...]:
    segmented = _segment_blocks(lines)
    blocks: List[Block] = []
    for index, grouped_lines in enumerate(segmented, start=1):
        score_vector = _initial_block_scores(grouped_lines)
        top_type = _top_type(score_vector)
        blocks.append(
            Block(
                block_id=f"block-{index:04d}",
                lines=grouped_lines,
                score_vector=score_vector,
                constraints=_build_constraints(score_vector),
                style=StyleProfile(block_type=top_type),
                parser_diagnostics={
                    "pass2_top_type_index": float(BLOCK_TYPES.index(top_type)),
                    "line_count": float(len(grouped_lines)),
                },
            )
        )
    return tuple(blocks)


def _pass3_refine(blocks: Sequence[Block]) -> Tuple[Block, ...]:
    if not blocks:
        return tuple()

    top_counts: Dict[str, int] = {block_type: 0 for block_type in BLOCK_TYPES}
    for block in blocks:
        top_counts[_top_type(block.score_vector)] += 1
    total = float(len(blocks))
    prevalence = {
        block_type: (top_counts[block_type] / total) for block_type in BLOCK_TYPES
    }

    refined: List[Block] = []
    for block in blocks:
        scores = dict(block.score_vector)
        original = dict(scores)
        top_before = _top_type(scores)

        for block_type in BLOCK_TYPES:
            adjustment = prevalence[block_type] * 0.08
            if block_type == top_before:
                adjustment += 0.05
            scores[block_type] += adjustment

        normalized = _normalize_scores(scores)
        delta_sum = sum(normalized[key] - original[key] for key in BLOCK_TYPES)
        top_after = _top_type(normalized)

        refined.append(
            Block(
                block_id=block.block_id,
                lines=block.lines,
                score_vector=normalized,
                constraints=_build_constraints(normalized),
                style=StyleProfile(block_type=top_after, tags=block.style.tags),
                parser_diagnostics={
                    **block.parser_diagnostics,
                    "pass3_top_type_index": float(BLOCK_TYPES.index(top_after)),
                    "pass3_delta_sum": delta_sum,
                    "pass3_prevalence_top": prevalence[top_after],
                },
            )
        )

    return tuple(refined)


def ingest_content(
    content: str, markdown: bool, source_path: Optional[Path] = None
) -> Document:
    """Ingest source content into the common internal document model.

    This intake pipeline applies three deterministic passes:
    1) line-local feature extraction, 2) block segmentation and scoring,
    and 3) document-level refinement. Source fidelity is preserved.
    """

    trailing_newline = content.endswith(("\n", "\r\n"))
    lines = _pass1_lines(content.splitlines())
    pass2_blocks = _pass2_blocks(lines)
    blocks = _pass3_refine(pass2_blocks)

    return Document(
        blocks=blocks,
        source_markdown=markdown,
        trailing_newline=trailing_newline,
        source_path=source_path,
        original_text=content,
        metadata={
            "intake_pipeline": "three_pass",
            "block_type_count": str(len(BLOCK_TYPES)),
        },
    )

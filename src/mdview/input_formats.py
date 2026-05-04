"""Buffered-stdin format detection helpers.

The stdin path needs conservative format detection because piped content often
starts life as generic process output. Detect Markdown only when there is clear
structure; otherwise keep stdin in plain-text mode so mdview does not
accidentally reflow arbitrary text.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Callable, Optional, Sequence

_FALLBACK_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_FALLBACK_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+\S")
_FALLBACK_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s+\S")
_FALLBACK_RULE_RE = re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$")
_FALLBACK_FENCE_RE = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")
_FALLBACK_LINK_RE = re.compile(r"\[[^\]\n]+\]\([^)]+\)")
_FALLBACK_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\([^)]+\)")
_FALLBACK_CODE_RE = re.compile(r"`[^`\n]+`")
_FALLBACK_STRONG_RE = re.compile(r"(?<!\\)(?:\*\*|__)\S.*?(?:\*\*|__)")
_FALLBACK_STRIKETHROUGH_RE = re.compile(r"~~[^~\n]+~~")
_EXPLICIT_BLOCK_TOKEN_TYPES = {
    "blockquote_open",
    "bullet_list_open",
    "code_block",
    "fence",
    "heading_open",
    "hr",
    "html_block",
    "ordered_list_open",
    "table_open",
}
_EXPLICIT_INLINE_TOKEN_TYPES = {
    "code_inline",
    "em_open",
    "hardbreak",
    "html_inline",
    "image",
    "link_open",
    "s_open",
    "strong_open",
}


@dataclass(frozen=True)
class DetectedInputFormat:
    """Detected format metadata for one buffered stdin document."""

    name: str
    markdown: bool


FormatDetector = Callable[[str], Optional[DetectedInputFormat]]

MARKDOWN_INPUT_FORMAT = DetectedInputFormat(name="markdown", markdown=True)
PLAIN_TEXT_INPUT_FORMAT = DetectedInputFormat(name="plain_text", markdown=False)


def detect_input_format(content: str) -> DetectedInputFormat:
    """Return the first recognized buffered-stdin format for ``content``."""

    for detector in _format_detectors():
        detected = detector(content)
        if detected is not None:
            return detected
    return PLAIN_TEXT_INPUT_FORMAT


def _format_detectors() -> Sequence[FormatDetector]:
    """Return the ordered detector list for future format expansion."""

    return (_detect_markdown_input_format,)


def _detect_markdown_input_format(content: str) -> Optional[DetectedInputFormat]:
    """Return Markdown when the buffer has clear, valid Markdown structure."""

    stripped = content.strip()
    if not stripped:
        return None

    parser = _markdown_parser()
    if parser is not None and _tokens_contain_explicit_markdown(parser.parse(content)):
        return MARKDOWN_INPUT_FORMAT

    if _fallback_patterns_detect_markdown(content):
        return MARKDOWN_INPUT_FORMAT
    return None


@lru_cache(maxsize=1)
def _markdown_parser():
    """Return a cached Markdown parser when the optional runtime is present."""

    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    return MarkdownIt("default")


def _tokens_contain_explicit_markdown(tokens: Sequence[object]) -> bool:
    """Return whether parsed tokens include explicit Markdown constructs."""

    for token in tokens:
        token_type = getattr(token, "type", "")
        if token_type in _EXPLICIT_BLOCK_TOKEN_TYPES:
            return True
        for child in getattr(token, "children", ()) or ():
            child_type = getattr(child, "type", "")
            if child_type in _EXPLICIT_INLINE_TOKEN_TYPES:
                return True
    return False


def _fallback_patterns_detect_markdown(content: str) -> bool:
    """Return whether raw text matches supported Markdown structure patterns."""

    if _FALLBACK_LINK_RE.search(content) or _FALLBACK_IMAGE_RE.search(content):
        return True
    if _FALLBACK_CODE_RE.search(content) or _FALLBACK_STRONG_RE.search(content):
        return True
    if _FALLBACK_STRIKETHROUGH_RE.search(content):
        return True

    for line in content.splitlines():
        if _FALLBACK_HEADING_RE.match(line):
            return True
        if _FALLBACK_LIST_RE.match(line):
            return True
        if _FALLBACK_BLOCKQUOTE_RE.match(line):
            return True
        if _FALLBACK_RULE_RE.match(line):
            return True
        if _FALLBACK_FENCE_RE.match(line):
            return True
    return False

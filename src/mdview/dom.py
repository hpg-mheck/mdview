"""Common internal document object model for mdview content pipelines."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ConstraintProfile:
    """Hard and soft behavioral constraints attached to a content block."""

    no_reflow: bool = False
    minimum_width: int = 0
    preserve_indentation: bool = False
    wrap_hint: str = "auto"


@dataclass(frozen=True)
class StyleProfile:
    """Semantic style metadata for a content block."""

    block_type: str = "plain"
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Line:
    """Single source line with fidelity and display metadata."""

    source_text: str
    normalized_text: str
    display_width: int
    hard_break: bool = True
    feature_vector: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_source(
        cls,
        text: str,
        *,
        display_width: Optional[int] = None,
        feature_vector: Optional[Dict[str, float]] = None,
    ) -> "Line":
        """Construct a line from source text while preserving text fidelity."""

        return cls(
            source_text=text,
            normalized_text=text,
            display_width=len(text) if display_width is None else display_width,
            hard_break=True,
            feature_vector={} if feature_vector is None else feature_vector,
        )


@dataclass(frozen=True)
class Block:
    """Ordered collection of lines with classification metadata."""

    block_id: str
    lines: Tuple[Line, ...]
    score_vector: Dict[str, float] = field(default_factory=dict)
    constraints: ConstraintProfile = field(default_factory=ConstraintProfile)
    style: StyleProfile = field(default_factory=StyleProfile)
    parser_diagnostics: Dict[str, float] = field(default_factory=dict)

    def to_source_text(self) -> str:
        """Return source text reconstructed from this block."""

        return "\n".join(line.source_text for line in self.lines)


@dataclass(frozen=True)
class Document:
    """Top-level content model shared by intake, rendering, and viewer layers."""

    blocks: Tuple[Block, ...]
    source_markdown: bool
    trailing_newline: bool
    source_path: Optional[Path] = None
    original_text: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_source_text(self) -> str:
        """Return the original source text with line boundaries preserved."""

        if self.original_text:
            return self.original_text

        text = "\n\n".join(block.to_source_text() for block in self.blocks)
        if self.trailing_newline and not text.endswith("\n"):
            text += "\n"
        return text

    @property
    def lines(self) -> List[Line]:
        """Return all lines across blocks in source order."""

        collected: List[Line] = []
        for block in self.blocks:
            collected.extend(block.lines)
        return collected

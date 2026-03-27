#!/usr/bin/env python3
"""Compare mdview's managed AGENTS.md sections with TheKnowledge templates."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Sequence

from _theknowledge_delegate import REPO_ROOT, load_script_module


MODULE = load_script_module("initial_setup.py")

HEADER_START = "<!-- THEKNOWLEDGE_MANAGED_HEADER_START -->"
HEADER_END = "<!-- THEKNOWLEDGE_MANAGED_HEADER_END -->"
FOOTER_START = "<!-- THEKNOWLEDGE_MANAGED_FOOTER_START -->"
FOOTER_END = "<!-- THEKNOWLEDGE_MANAGED_FOOTER_END -->"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare mdview's managed AGENTS.md header and footer with the "
            "current TheKnowledge templates."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="Project root whose AGENTS.md should be checked.",
    )
    parser.add_argument(
        "--knowledge-root",
        default="TheKnowledge",
        help="Path from the project root to the TheKnowledge checkout.",
    )
    return parser.parse_args(argv)


def extract_managed_block(content: str, start_marker: str, end_marker: str) -> str:
    if start_marker not in content or end_marker not in content:
        return ""
    start = content.index(start_marker)
    end = content.index(end_marker) + len(end_marker)
    block = content[start:end].strip()
    if block:
        return block + "\n"
    return ""


def render_expected_block(
    templates_root: Path,
    template_name: str,
    knowledge_root: str,
) -> str:
    return MODULE.render_file(templates_root / template_name, knowledge_root).decode(
        "utf-8"
    )


def print_diff(label: str, current: str, expected: str) -> None:
    diff = list(
        difflib.unified_diff(
            current.splitlines(),
            expected.splitlines(),
            fromfile=f"current-{label}",
            tofile=f"expected-{label}",
            lineterm="",
        )
    )
    if diff:
        print(f"[managed-drift] DIFF {label}:")
        for line in diff:
            print(line)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve()
    knowledge_root = args.knowledge_root
    templates_root = (project_root / knowledge_root / "templates").resolve()
    if not templates_root.is_dir():
        print(
            f"[managed-drift] FAIL: missing templates dir {templates_root}",
            file=sys.stderr,
        )
        return 2

    agents_path = project_root / MODULE.AGENTS_PATH
    if not agents_path.is_file():
        print(
            f"[managed-drift] FAIL: missing {agents_path.relative_to(project_root)}",
            file=sys.stderr,
        )
        return 2

    content = agents_path.read_text(encoding="utf-8")
    current_header = extract_managed_block(content, HEADER_START, HEADER_END)
    current_footer = extract_managed_block(content, FOOTER_START, FOOTER_END)
    expected_header = render_expected_block(
        templates_root,
        MODULE.AGENTS_HEADER,
        knowledge_root,
    )
    expected_footer = render_expected_block(
        templates_root,
        MODULE.AGENTS_FOOTER,
        knowledge_root,
    )

    drift_found = False
    print(
        f"[managed-drift] Project root: {project_root}\n"
        f"[managed-drift] Knowledge root: {knowledge_root}"
    )

    for label, current, expected in (
        ("header", current_header, expected_header),
        ("footer", current_footer, expected_footer),
    ):
        if current == expected:
            print(f"[managed-drift] OK: managed {label} is up to date.")
            continue
        drift_found = True
        if not current:
            print(f"[managed-drift] WARN: managed {label} block is missing.")
        else:
            print(f"[managed-drift] WARN: managed {label} differs.")
        print_diff(label, current, expected)

    if drift_found:
        print(
            "[managed-drift] NEXT: review the diffs above, then refresh the "
            "managed sections with:"
        )
        print("[managed-drift] NEXT: python scripts/refresh_managed_agents.py")
        print(
            "[managed-drift] NEXT: run `git diff` before any `git add` so "
            "the staged update is reviewed first."
        )
        return 1

    print("[managed-drift] PASS: managed AGENTS.md sections match current templates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

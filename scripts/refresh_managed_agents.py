#!/usr/bin/env python3
"""Refresh mdview's managed AGENTS.md sections from TheKnowledge templates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from _theknowledge_delegate import REPO_ROOT, load_script_module


MODULE = load_script_module("initial_setup.py")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh only the managed AGENTS.md header and footer from "
            "TheKnowledge templates."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="Project root whose AGENTS.md should be refreshed.",
    )
    parser.add_argument(
        "--knowledge-root",
        default="TheKnowledge",
        help="Path from the project root to the TheKnowledge checkout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the target file without rewriting AGENTS.md.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve()
    templates_root = (project_root / args.knowledge_root / "templates").resolve()
    if not templates_root.is_dir():
        print(
            f"[refresh-managed-agents] FAIL: missing templates dir {templates_root}",
            file=sys.stderr,
        )
        return 1

    destination = MODULE.install_agents_file(
        templates_root=templates_root,
        project_root=project_root,
        knowledge_root=args.knowledge_root,
        dry_run=args.dry_run,
    )
    action = "would refresh" if args.dry_run else "refreshed"
    print(
        "[refresh-managed-agents] PASS: "
        f"{action} {destination.relative_to(project_root).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

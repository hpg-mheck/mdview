#!/usr/bin/env python3
"""Validate demo Markdown documents with per-file hash caching."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mdview import rendering  # noqa: E402
from mdview.rendering import render_to_ansi  # noqa: E402

SCHEMA_VERSION = "1.0.0"
DEFAULT_CACHE_FILE = ".git/mdview-demo-validation-cache.json"
DEFAULT_RENDER_WIDTH = 120
ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+\S", re.MULTILINE)
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
INLINE_COLOR_SPAN_RE = re.compile(
    r"<span\b(?P<attrs>[^>]*)>(?P<body>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class DemoFile:
    demo_root: Path
    path: Path

    @property
    def logical_name(self) -> str:
        return self.path.relative_to(self.demo_root).as_posix()


@dataclass(frozen=True)
class ColorExpectation:
    text: str
    foreground: str


@dataclass
class ValidationSummary:
    errors: List[str]
    checked_color_spans: int

    @property
    def status(self) -> str:
        if self.errors:
            return "fail"
        return "pass"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Markdown demo documents using per-file content hash cache."
        )
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root that may contain a top-level demos/ directory.",
    )
    parser.add_argument(
        "--cache-file",
        default=DEFAULT_CACHE_FILE,
        help="Cache file path relative to --project-root.",
    )
    parser.add_argument(
        "--render-width",
        type=int,
        default=DEFAULT_RENDER_WIDTH,
        help="Render width for demo validation.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached file hashes and revalidate all discovered demos.",
    )
    parser.add_argument(
        "--show-cache",
        action="store_true",
        help="Print the current cache JSON and exit.",
    )
    return parser.parse_args(argv)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_git_dir(project_root: Path) -> Path:
    git_path = project_root / ".git"
    if git_path.is_dir():
        return git_path.resolve()

    if git_path.is_file():
        header = git_path.read_text(encoding="utf-8").strip()
        if header.startswith("gitdir:"):
            raw_git_dir = header.split(":", 1)[1].strip()
            git_dir = Path(raw_git_dir)
            if not git_dir.is_absolute():
                git_dir = (project_root / git_dir).resolve()
            return git_dir

    return git_path.resolve()


def resolve_cache_path(project_root: Path, value: str) -> Path:
    if value.startswith(".git/"):
        return resolve_git_dir(project_root) / value.split("/", 1)[1]

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def load_cache(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "files": {}}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "files": {}}
    if data.get("schema_version") != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        data["files"] = {}
    return data


def save_cache(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {
        "schema_version": SCHEMA_VERSION,
        "files": data.get("files", {}),
    }
    path.write_text(
        json.dumps(ordered, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def collect_demo_files(project_root: Path) -> List[DemoFile]:
    demo_root = (project_root / "demos").resolve()
    if not demo_root.exists():
        return []

    files: List[DemoFile] = []
    for path in sorted(demo_root.rglob("*.md")):
        if path.is_file():
            files.append(DemoFile(demo_root=demo_root, path=path.resolve()))
    return files


def prune_cache(files_cache: Dict[str, object], active_keys: set[str]) -> None:
    stale = [key for key in files_cache if key not in active_keys]
    for key in stale:
        files_cache.pop(key, None)


def emit_error(message: str) -> None:
    print(f"[demo-check] ERROR: {message}", file=sys.stderr)


def validate_markdown(text: str) -> List[str]:
    errors: List[str] = []
    if not text.strip():
        errors.append("document is empty")
        return errors
    if not text.endswith("\n"):
        errors.append("document must end with a trailing newline")
    if "\t" in text:
        errors.append("tabs are not allowed in demo documents")
    if ATX_HEADING_RE.search(text) is None:
        errors.append("document must include at least one ATX heading")

    fence_char: str | None = None
    fence_length = 0
    fence_line = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if fence_char is None:
            match = FENCE_RE.match(line)
            if match:
                token = match.group(1)
                fence_char = token[0]
                fence_length = len(token)
                fence_line = line_number
            continue

        closing_pattern = rf"^[ \t]*{re.escape(fence_char)}{{{fence_length},}}[ \t]*$"
        if re.match(closing_pattern, line):
            fence_char = None
            fence_length = 0
            fence_line = 0

    if fence_char is not None:
        errors.append(f"unclosed fenced code block opened on line {fence_line}")
    return errors


def collect_color_expectations(text: str) -> Tuple[List[ColorExpectation], List[str]]:
    expectations: List[ColorExpectation] = []
    errors: List[str] = []
    for match in INLINE_COLOR_SPAN_RE.finditer(text):
        color_value = rendering._extract_span_color_value(match.group("attrs"))
        if color_value is None:
            continue

        rgb = rendering._normalize_span_color_value(color_value)
        if rgb is None:
            errors.append(f"unsupported span color value: {color_value}")
            continue

        body = HTML_TAG_RE.sub("", match.group("body")).strip()
        if not body:
            errors.append(f"color span with {color_value!r} must contain visible text")
            continue
        if "\n" in body:
            errors.append(f"color span for {body!r} must stay on one rendered line")
            continue

        expectations.append(
            ColorExpectation(
                text=body,
                foreground="#{:02x}{:02x}{:02x}".format(*rgb),
            )
        )
    return expectations, errors


def capture_ansi_cell_rows(ansi_text: str) -> List[List[Dict[str, object]]]:
    rows: List[List[Dict[str, object]]] = []
    for row_index, line in enumerate(ansi_text.splitlines() or [""]):
        row_cells: List[Dict[str, object]] = []
        column_index = 0
        for style, text in rendering._ansi_line_to_formatted_segments(line):
            for character in text:
                row_cells.append(
                    rendering._make_cell_snapshot(
                        row=row_index,
                        column=column_index,
                        character=character,
                        style_value=style,
                    )
                )
                column_index += 1
        rows.append(row_cells)
    return rows


def row_ascii(cells: Sequence[Dict[str, object]]) -> str:
    return "".join(str(cell.get("character_ascii", " "))[:1] for cell in cells)


def row_has_expected_color(
    cells: Sequence[Dict[str, object]], text: str, foreground: str
) -> bool:
    line = row_ascii(cells)
    start = line.find(text)
    while start != -1:
        stop = start + len(text)
        if stop <= len(cells) and all(
            cells[index].get("attributes", {}).get("foreground") == foreground
            for index in range(start, stop)
        ):
            return True
        start = line.find(text, start + 1)
    return False


def validate_demo(demo: DemoFile, render_width: int) -> ValidationSummary:
    text = demo.path.read_text(encoding="utf-8")
    errors = validate_markdown(text)
    expectations, span_errors = collect_color_expectations(text)
    errors.extend(span_errors)

    try:
        rendered = render_to_ansi(text, markdown=True, width=max(render_width, 40))
    except Exception as exc:  # pragma: no cover - defensive path
        errors.append(f"rendering raised {type(exc).__name__}: {exc}")
        return ValidationSummary(errors=errors, checked_color_spans=len(expectations))

    if not rendered.strip():
        errors.append("rendered output is empty")
    if "<span" in rendered.lower():
        errors.append("rendered output leaked raw HTML span tags")

    if expectations:
        cell_rows = capture_ansi_cell_rows(rendered)
        for expectation in expectations:
            if not any(
                row_has_expected_color(
                    cells,
                    expectation.text,
                    expectation.foreground,
                )
                for cells in cell_rows
            ):
                errors.append(
                    "expected rendered color {foreground} for text {text!r}".format(
                        foreground=expectation.foreground,
                        text=expectation.text,
                    )
                )

    return ValidationSummary(errors=errors, checked_color_spans=len(expectations))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_root = Path(args.project_root).resolve()
    cache_path = resolve_cache_path(project_root, args.cache_file)

    if not project_root.exists():
        emit_error(f"missing project root: {project_root}")
        return 2

    cache = load_cache(cache_path)
    files_cache = cache.setdefault("files", {})
    if not isinstance(files_cache, dict):
        files_cache = {}
        cache["files"] = files_cache

    if args.show_cache:
        print(json.dumps(cache, indent=2, sort_keys=False))
        return 0

    demo_files = collect_demo_files(project_root)
    active_keys = {demo.logical_name for demo in demo_files}
    prune_cache(files_cache, active_keys)

    if not demo_files:
        save_cache(cache_path, cache)
        print("[demo-check] PASS: no demo Markdown files found.")
        return 0

    validated = 0
    skipped = 0
    errors_seen = 0

    for demo in demo_files:
        digest = sha256_digest(demo.path)
        cache_entry = files_cache.get(demo.logical_name)
        if (
            not args.no_cache
            and isinstance(cache_entry, dict)
            and cache_entry.get("sha256") == digest
            and cache_entry.get("status") == "pass"
        ):
            skipped += 1
            print(f"[demo-check] SKIP: {demo.logical_name}")
            continue

        summary = validate_demo(demo, render_width=args.render_width)
        validated += 1
        errors_seen += len(summary.errors)

        if summary.errors:
            emit_error(f"validation failed for {demo.logical_name}")
            for message in summary.errors:
                emit_error(f"  {message}")
        else:
            print(f"[demo-check] PASS: {demo.logical_name}")

        files_cache[demo.logical_name] = {
            "status": summary.status,
            "sha256": digest,
            "checked_color_spans": summary.checked_color_spans,
            "errors": summary.errors,
            "updated_at": now_iso(),
        }

    save_cache(cache_path, cache)
    print(
        "[demo-check] SUMMARY: "
        f"validated={validated} skipped={skipped} errors={errors_seen}"
    )
    if errors_seen:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

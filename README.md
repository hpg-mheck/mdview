# mdview

A console-first Markdown viewer with an internal rendering and viewing
engine. mdview renders headings, emphasis, and code blocks with ANSI styling
so Markdown reads naturally in the terminal.

## Features
- Renders Markdown using the
  [`rich`](https://github.com/Textualize/rich) library for readable terminal
  formatting.
- Uses an internal viewport with integrated vertical and horizontal
  navigation.
- Supports `.md`, `.markdown`, and `.txt` input out of the box.
- Minimal runtime dependencies; packaged for Python 3.9+.
- Graceful fallback to plain-text output if `rich` is unavailable in the
  environment.
- Provides stateful mode-switching helpers intended for a `<META>+W` hotkey
  that toggles word wrap against horizontal scrolling while preserving search
  anchors.

## Installation
For repository development, use the managed bootstrap flow:
```bash
./install.sh --mode dev
```

For a user-local non-development install, use:
```bash
./install.sh
```

The legacy `./bootstrap.sh` and `./scripts/install_prerequisites.sh` entry
points remain available as compatibility wrappers to `./install.sh`.
On Unix-like hosts, development mode provisions the configured pyenv
selections, refreshes `.venv`, and enables direnv-backed project activation.
If non-interactive automation must force the optional dev-launcher choice,
set `MDVIEW_DEV_LAUNCHER_MODE=local` or `MDVIEW_DEV_LAUNCHER_MODE=system`.

For an editable install without the full bootstrap flow:
```bash
pip install .
```

For development:
```bash
pip install -e .[dev]
```

## Usage
Render one or more files in your terminal with full navigation (arrows,
Page Up/Down, `n`/`p` or `:n`/`:p` for next/previous document, `q` quit):
```bash
mdview path/to/file-a.md path/to/file-b.md
```

When developing from a clone, prefer the repository-local launcher so PATH
shims from other Python environments cannot interfere:
```bash
./mdview path/to/file-a.md
```

Optional flags:
- `--reflow` to enable reflow processing using `--reflow-mode prose`
  unless another mode is specified.
- `--reflow-mode prose|all|none` to select policy behavior.
- `--noreflow` to disable reflow in all cases (`--reflow-mode none`).
- `--verbose` to report operational events such as document switches.
- `--MIL` to emit Monkey-in-the-Loop action telemetry for live
  troubleshooting.
- `--readability-first-tables` to keep Markdown tables at readable column
  widths even when that means horizontal overflow.
- `--no-table-borders` to suppress the outer gray border around Markdown
  tables.
- `--no-cell-borders` to suppress the internal gray cell separators within
  Markdown tables.
- `--automation-timeout <seconds>` to inject synthetic quit after a bounded
  viewer runtime during unattended automation.
- `--automation-timeout-screenshot <basename>` to store timeout-exit
  framebuffer artifacts as `<basename>.txt` and `<basename>.attrs.json`
  (defaults to `./mdview-automation-timeout-framebuffer` when timeout is
  enabled).
- `--screen-dump-dir <path>` to choose where interactive `!` captures write
  `mdview-screen.txt` and `mdview-screen.attrs.json`.
- `--automation-json <source>` to replay timed key input as
  `[[delay_seconds, key_spec], ...]` from a JSON file path or literal JSON
  string.
- `--redraw-check-digit` to overlay a center-screen digit that advances
  modulo 10 on each interactive pager redraw.
- `--viewport-columns <int>` and `--viewport-rows <int>` to enforce synthetic
  viewport dimensions for deterministic automation captures.
- `--verify-resize-detection` to run an interactive resize checklist that
  acknowledges detected events and reports PASS/FAIL per step.
- `--test-input-feedback` to run a two-stage terminal input diagnostic that
  compares direct stdin handling against the prompt_toolkit viewer stack while
  logging timestamped input and redraw events.
- `--version` to display the current version.

Viewport movement behavior and automation replay format are documented in
`docs/movement.txt`.

While viewing interactively, press `!` to dump the current visible viewport as
paired text and JSON framebuffer artifacts.

Bundled demos live under `demos/`. For a quick feature tour, run:
```bash
./mdview demos/table-demo.md
```

To make full-screen redraws visible during normal viewing sessions, run:
```bash
mdview --redraw-check-digit path/to/file.md
```
The interactive pager will replace the center cell with a digit that advances
from `0` to `9` on each redraw.

For terminal key-diagnostics, run:
```bash
mdview --test-input-feedback
```
Stage 1 redraws a ten-cell dash bar on new lines using direct terminal input.
Stage 2 repeats the same movement test in a full-screen prompt_toolkit view.
Both stages accept Left/Right arrows plus `,` and `.` alternates, and emit
timestamped debug logs to standard error.

Markdown content reflows to current window dimensions by default.
`--reflow` is therefore redundant for Markdown. The exception is Markdown
tables: they may exceed viewport width when minimum table sizing requires it.
By default, recognized Markdown tables render as gray boxed grids using
Unicode box-drawing characters. Use `--no-table-borders` and/or
`--no-cell-borders` to replace those border layers with whitespace gaps.
When any rendered line exceeds viewport width, a horizontal scrollbar
becomes active and left/right arrow keys pan the viewport.

For plain-text (`.txt`) files without explicit reflow flags, mdview preserves
source line breaks by default. Reflow for `.txt` content is opt-in via
`--reflow` or explicit `--reflow-mode`.

Windows 11 workflow shortcuts:
- Bootstrap environment:
  - PowerShell:
    `powershell -ExecutionPolicy Bypass -File scripts/windows/bootstrap.ps1`
  - cmd.exe:
    `scripts\\windows\\bootstrap.bat`
- Run required checks:
  - PowerShell:
    `powershell -ExecutionPolicy Bypass -File scripts/windows/run-tool.ps1`
    `pytest`
  - cmd.exe:
    `scripts\\windows\\run-tool.bat pytest`

## Project Structure
- `demos/` - Showcase Markdown documents validated through the cached
  `demo_check` workflow.
- `src/mdview/` – Library code for rendering and paging.
- `docs/specifications/` – Written specifications and architecture notes.
- `tests/` – Pytest-based unit tests covering the rendering pipeline and pager
  integration hooks.

## Contributing
- Keep code small, focused, and well-documented with type hints.
- Prefer standard library facilities and minimal external dependencies.
- Add or update tests alongside any code changes.

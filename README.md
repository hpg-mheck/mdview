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
```bash
pip install .
```

For development:
```bash
pip install -e .[dev]
```

## Usage
Render a file in your terminal with full navigation (arrows,
Page Up/Down, `/` search, `n`/`N` next/previous, `q` to quit):
```bash
mdview path/to/file.md
```

Optional flags:
- `--reflow` to enable reflow processing using `--reflow-mode prose`
  unless another mode is specified.
- `--reflow-mode prose|all|none` to select policy behavior.
- `--noreflow` to disable reflow in all cases (`--reflow-mode none`).
- `--version` to display the current version.

Markdown content reflows to current window dimensions by default.
`--reflow` is therefore redundant for Markdown. The exception is Markdown
tables: they may exceed viewport width when minimum table sizing requires it.
When any rendered line exceeds viewport width, a horizontal scrollbar becomes
active and left/right arrow keys pan the viewport.

For plain-text (`.txt`) files without explicit reflow flags, mdview preserves
source line breaks by default. Reflow for `.txt` content is opt-in via
`--reflow` or explicit `--reflow-mode`.

## Project Structure
- `src/mdview/` – Library code for rendering and paging.
- `docs/specifications/` – Written specifications and architecture notes.
- `tests/` – Pytest-based unit tests covering the rendering pipeline and pager
  integration hooks.

## Contributing
- Keep code small, focused, and well-documented with type hints.
- Prefer standard library facilities and minimal external dependencies.
- Add or update tests alongside any code changes.

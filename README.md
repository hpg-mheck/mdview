# mdview

A console-first Markdown viewer that pipes styled output into a familiar
`less`-like interface. mdview renders headings, emphasis, and code blocks with
ANSI styling so Markdown reads naturally in the terminal.

## Features
- Renders Markdown using the
  [`rich`](https://github.com/Textualize/rich) library for readable terminal
  formatting.
- Delegates navigation and search to `less` (via `pydoc.pager`) for
  muscle-memory-friendly controls.
- Supports `.md`, `.markdown`, and `.txt` input out of the box.
- Minimal runtime dependencies; packaged for Python 3.8+.
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
Render a file in your terminal with full `less` navigation (arrows,
Page Up/Down, `/` search, `n`/`N` next/previous, `q` to quit):
```bash
mdview path/to/file.md
```

Optional flags:
- `--pager "<command>"` to override the pager (defaults to `less -R` through
  `pydoc.pager`).
- `--version` to display the current version.

If `less` is unavailable, mdview falls back to the default pager provided
by the Python standard library; output remains readable though navigation may
be more limited.

## Project Structure
- `src/mdview/` – Library code for rendering and paging.
- `docs/specifications/` – Written specifications and architecture notes.
- `tests/` – Pytest-based unit tests covering the rendering pipeline and pager
  integration hooks.

## Contributing
- Keep code small, focused, and well-documented with type hints.
- Prefer standard library facilities and minimal external dependencies.
- Add or update tests alongside any code changes.

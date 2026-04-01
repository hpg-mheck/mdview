# Terminal Table Demo

mdview can show a dense Markdown status board without leaving the terminal.
This demo mixes tables, color spans, links, lists, block quotes, and fenced
code so operators have something realistic to inspect.

> Press `!` during interactive viewing to capture the visible framebuffer and
> compare the styled output against the JSON attribute dump.

## Highlights

- Bold labels like **READY** still read cleanly in ANSI output.
- Inline code such as `./mdview demos/table-demo.md` stays aligned with the
  surrounding prose.
- The table below uses named colors, hex colors, and `rgb(...)` colors.

## Status Board

| Area   | State                                |  ms | Note     |
| :----- | :----------------------------------- | -: | :------- |
| Parser | <span style="color: green">READY</span> |  12 | Stable   |
| Render | <span style="color: #f70">WARM</span>   |  21 | Profiles |
| Alerts | <span style="color: #f44">HOT</span>    |  03 | Armed    |
| Links  | <span style="color: blue">LIVE</span>   |  09 | OSC      |

## Tactics

1. Open the demo with `./mdview demos/table-demo.md`.
2. Pan horizontally if the table overflows the current viewport.
3. Press `!` to dump the visible framebuffer as text and JSON.

## Sample Command

```bash
./mdview --redraw-check-digit --screen-dump-dir /tmp demos/table-demo.md
```

## Mixed Formatting

The footer keeps one extra accent in
<span style="color: cyan">cool blue-green light</span> while linking to the
[Rich documentation](https://github.com/Textualize/rich) for reference.

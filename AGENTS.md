# Engineering Guidance

This project follows pragmatic Python best practices with an emphasis on
portability (assume Python 3.9+ compatibility when writing or reviewing code)
and pessimistic, defense-in-depth testing.

Start every engagement by reading `docs/development-workflow.txt` for a
high-level overview of how to work within this repository. Treat it as the
first stop for understanding proposals, backlog handling, and execution steps
before diving into other materials.
Read `project-management/git-flow.txt` for branch naming and merge SOP before
creating branches or performing integration work.
Then check `.git/codex-local-notes.txt` for operator-provided local-only
environment notes that must not be committed.

## Style and Documentation
- Write clear, direct prose that aligns with the Chicago Manual of Style. Keep
  documentation focused, actionable, and concise.
- Prefer explicit, self-documenting code. Avoid cleverness that obscures
  intent.
- Maintain compatibility with Python 3.9+ constructs and standard library
  features unless explicitly justified otherwise.
- Comment sparingly but meaningfully: explain *why* rather than *what* when
  intent is non-obvious.

# Contribution Guidelines
- Write feature specifications **before** implementing tests or production
  code.
- Store all specifications as plain text under `docs/specifications/`.
- Follow existing documentation style and keep specs concise, actionable, and
  testable.
- Wrap user documentation and project specification text files to 78 columns.
  This applies to all text files except those under `resources/tests` or
  `resources/testing` that are used for test data.
- After modifying any text files outside `resources/tests` or
  `resources/testing`, verify they comply with the 78-column wrap rule.

## Project Management Orders
- Maintain `/project-management/state/backlog.txt` as the ordered source of
  pending work. The top item is always next up; the bottom item waits the
  longest.
  Mark each task with an asterisk followed by a blank line for clarity.
  Explicitly note when a task is blocked and identify what or whom it depends
  on. Include a timestamp in ISO 8601 format indicating when the item was
  added.
- Keep `/project-management/state/tasks-in-progress.txt` nearly empty. Use it
  only for tasks actively being implemented, following the same asterisk and
  blank-line formatting. Include brief status notes and cite blockers. Move
  entries back to the backlog or into completed tasks as soon as possible.
  Record the timestamp for when the task entered this list.
- Record finished work in `/project-management/state/completed-tasks.txt`,
  placing the most recently completed item at the top. Preserve the
  asterisk-plus-blank-line formatting, and include concise context such as
  dates, responsible
  contributors, and how any blockers were cleared. Stamp each completion with
  the time it was added to the list.
- Treat the three project management files as living documents. Update them
  immediately when work status changes, and keep descriptions concise and
  actionable per Chicago Manual of Style guidance.
- Maintain `/project-management/state/ai-human-requests.txt` as the queue for
  non-blocking requests that AI agents need human operators to handle. Keep
  entries in the `Pending Requests`, `Active Requests`, and
  `Completed Requests` sections.
- Keep proposal files in status folders under
  `/project-management/state/proposals/`:
  `pending/`, `accepted/`, `completed/`, `rejected/`, `superseded/`, and
  `under-review/`. Use `pending/` for new proposals unless an operator
  directs another initial state.
- AI agents should add new items to `Pending Requests` by default, using the
  same asterisk-plus-blank-line style and including concise context, owner,
  and ISO 8601 timestamps.
- Human operators are expected to move requests to `Completed Requests`, but
  AI agents should help keep the file current when completion is evident.
  If an AI believes a request is done but not updated, the AI should ask for
  operator confirmation when possible before moving the entry to completed.
- When an operator directs that a feature be deferred, move the item from
  `project-management/state/backlog.txt` or
  `project-management/state/tasks-in-progress.txt` into
  `project-management/state/deferred.txt`, preserving the
  asterisk-plus-blank-line formatting and recording why the deferral
  happened. Copy the original task language into a quoted block inside the
  deferred entry so it can return to the backlog verbatim when re-enabled.
  The quoted block starts with a line containing only `>>BEGIN>>`, ends with
  a line containing only `>>END>>`, and includes every line of the original
  text prefixed by `> `, including blank lines.
- Treat `/project-management/state/proposals/under-review/` as a hold area
  for debated proposals. AI agents must not auto-implement any proposal in
  that directory under any circumstances. Work in that directory is limited
  to proposal editing, review, and operator-directed status changes unless
  the operator explicitly moves the proposal out of `under-review`.

## Backlog Iteration Orders
- When instructed to "Iterate the backlog" or simply "iterate," follow the
  single AI iteration cycle defined in `docs/AI-backlog-iteration.txt` unless
  the prompt clearly names a different list (for example, "iterate on the
  buglist").

## Bug Tracking Orders
- Maintain `/project-management/state/bugs/known-bugs.txt` as the ordered
  source of confirmed issues awaiting work. Use the same
  asterisk-plus-blank-line formatting, include concise context, and stamp
  each entry with the time it was added.
- Track active remediation in
  `/project-management/state/bugs/bugs-in-progress.txt` with the same
  formatting, timestamping entries as they move into progress, and noting
  current owners and blockers.
- Record resolved items in `/project-management/state/bugs/closed-bugs.txt`,
  adding the newest items to the top, preserving the formatting, and
  including the completion timestamp and short resolution notes.
- Treat the three bug-tracking files as living documents. Update them as
  status changes, keeping entries succinct and actionable in line with the
  Chicago Manual of Style.
- When instructed to iterate on the buglist, treat the top item in
  `known-bugs.txt` like a backlog entry: perform one meaningful improvement,
  record ISO 8601 timestamps when moving items between bug files, and surface
  ownership or blocker updates.

## Testing Expectations
- Default to extensive, paranoid, pessimistic unit tests. Cover edge cases,
  error handling, and failure modes alongside happy paths.
- Derive tests from user stories and scenarios; keep them executable and
  reproducible.
- When adding features or fixing bugs, update or add tests before finalizing
  code. Never leave regressions unresolved.
- Store reusable test fixtures as static files under `resources/tests/` so
  automated scenarios can rely on consistent inputs.
- For broad exploratory smoke checks (for example, large random corpus runs),
  avoid one-off shell snippets. Use formal tests or reusable utilities under
  `dev-utils/`, and document usage/maintenance under `docs/testing/`.

## Cross-platform Windows Shim Verification Orders
- When changing Windows wrapper scripts (`scripts/windows/*.bat`,
  `scripts/windows/*.ps1`, or related Linux verification scripts), run:
  `python scripts/run_tool_with_timeout.py windows_shims_linux`
- Use the orchestrated Linux workflow in
  `docs/testing/windows/README.txt` and treat Windows CI as the final
  compatibility gate.
- Preferred local strategy on Linux: run rootless Podman + Wine preflight
  first, then run host Wine checks with a disposable `WINEPREFIX`.
- For AI agents: do not skip this workflow silently. If it returns `SKIP`,
  report the reason and proceed with normal checks so CI can verify on native
  Windows.

## Cross-platform Linux-from-Windows (WSL2) Verification Orders
- Treat `docs/specifications/testing/linux_validation_from_windows_wsl2.txt`
  as the contract for the mirrored Windows-host workflow.
- Do not execute WSL2 Linux-validation commands unless running on a real
  Windows host with WSL2 available.
- On non-Windows hosts, limit this area to specification and documentation
  changes only, and clearly report that execution validation is deferred.

## Required Local Checks (run before submitting any change)
1. Format and lint:
   - `python scripts/run_tool_with_timeout.py black`
   - `python scripts/run_tool_with_timeout.py ruff`
2. Static sanity:
   - `python scripts/run_tool_with_timeout.py compileall`
   - `python scripts/run_tool_with_timeout.py entropy_check`
   - `python scripts/run_tool_with_timeout.py entropy_tripwire_verify`
3. Tests:
   - `python scripts/run_tool_with_timeout.py pytest`

Additional cross-platform smoke check when Windows wrappers are touched:
- `python scripts/run_tool_with_timeout.py windows_shims_linux`

For standardized Git operations, prefer:
- `python scripts/git_standard_commit_push.py -m "<message>"` for commit/push
  (runs cached quality gate checks, including entropy tripwire verification,
  before push).
- `python scripts/git_veteran_pull.py` for guarded pull operations.
- Managed git hooks installed by `scripts/install_git_hooks.py` must include
  both `pre-commit` and `pre-push`; do not bypass them silently.
- Quality-gate cache path: `.git/mdview-quality-cache.json`. Use
  `--no-quality-cache` or `MDVIEW_QUALITY_GATE_NO_CACHE=1` only when an
  uncached rerun is explicitly required.

Use `python scripts/run_tool_with_timeout.py pytest -- -k <pattern>` to focus
on a subset of tests when iterating, but always run the full suite before
committing.

Timeout policy for AI agents:
- Invoke `black`, `ruff`, `compileall`, and `pytest` only through
  `scripts/run_tool_with_timeout.py`.
- Keep bailout timeouts short by default via `scripts/tool_timeouts.json`.
- Increase timeout values only when a short timeout demonstrably interrupts a
  valid run in progress.

Address any failures before committing. Document deviations explicitly in
commit messages.

## Fallback Notices and Documentation
- When mdview executes without optional dependencies, emit user-facing
  warnings describing the active fallback paths before the process exits.
- Keep `docs/specifications/fallback-behavior.txt` current with sections for
  each supported fallback. Add new entries there whenever additional fallbacks
  are introduced.
- Standing order: extend this section with concise bullets for every new
  fallback so expectations stay visible to contributors.

## Codex Log Handling Orders
- Do not inspect or process Codex build logs except when explicitly directed
  to "Analyze the latest Codex logs" for Codex-iteration optimization. Treat
  any other examination as out of scope.

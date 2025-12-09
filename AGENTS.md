# Engineering Guidance

This project follows pragmatic Python best practices with an emphasis on
portability (assume Python 3.7 compatibility when writing or reviewing code)
and pessimistic, defense-in-depth testing.

## Style and Documentation
- Write clear, direct prose that aligns with the Chicago Manual of Style. Keep
  documentation focused, actionable, and concise.
- Prefer explicit, self-documenting code. Avoid cleverness that obscures
  intent.
- Maintain compatibility with Python 3.7 constructs and standard library
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
- Maintain `/project-management/backlog.txt` as the ordered source of pending
  work. The top item is always next up; the bottom item waits the longest.
  Mark each task with an asterisk followed by a blank line for clarity.
  Explicitly note when a task is blocked and identify what or whom it depends
  on.
- Keep `/project-management/tasks-in-progress.txt` nearly empty. Use it only
  for tasks actively being implemented, following the same asterisk and
  blank-line formatting. Include brief status notes and cite blockers. Move
  entries back to the backlog or into completed tasks as soon as possible.
- Record finished work in `/project-management/completed-tasks.txt`, placing
  the most recently completed item at the top. Preserve the
  asterisk-plus-blank-line formatting, and include concise context such as
  dates, responsible
  contributors, and how any blockers were cleared.
- Treat the three project management files as living documents. Update them
  immediately when work status changes, and keep descriptions concise and
  actionable per Chicago Manual of Style guidance.

## Testing Expectations
- Default to extensive, paranoid, pessimistic unit tests. Cover edge cases,
  error handling, and failure modes alongside happy paths.
- Derive tests from user stories and scenarios; keep them executable and
  reproducible.
- When adding features or fixing bugs, update or add tests before finalizing
  code. Never leave regressions unresolved.
- Store reusable test fixtures as static files under `resources/tests/` so
  automated scenarios can rely on consistent inputs.

## Required Local Checks (run before submitting any change)
1. Format and lint:
   - `python -m black .`
   - `python -m ruff check .`
2. Static sanity:
   - `python -m compileall src tests`
3. Tests:
   - `python -m pytest`

Use `python -m pytest -k <pattern>` to focus on a subset of tests when
iterating, but always run the full suite before committing.

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

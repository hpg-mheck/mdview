# Engineering Guidance

This project follows pragmatic Python best practices with an emphasis on portability (assume Python 3.7 compatibility when writing or reviewing code) and pessimistic, defense-in-depth testing.

## Style and Documentation
- Write clear, direct prose that aligns with the Chicago Manual of Style. Keep documentation focused, actionable, and concise.
- Prefer explicit, self-documenting code. Avoid cleverness that obscures intent.
- Maintain compatibility with Python 3.7 constructs and standard library features unless explicitly justified otherwise.
- Comment sparingly but meaningfully: explain *why* rather than *what* when intent is non-obvious.

# Contribution Guidelines
- Write feature specifications **before** implementing tests or
  production code.
- Store all specifications as plain text under `docs/specifications/`.
- Follow existing documentation style and keep specs concise, actionable,
  and testable.
- Wrap user documentation and project specification text files to 78
  columns. This applies to all text files except those under
  `resources/tests` or `resources/testing` that are used for test data.
- After modifying any text files outside `resources/tests` or
  `resources/testing`, verify they comply with the 78-column wrap rule.

## Testing Expectations
- Default to extensive, paranoid, pessimistic unit tests. Cover edge cases, error handling, and failure modes alongside happy paths.
- Derive tests from user stories and scenarios; keep them executable and reproducible.
- When adding features or fixing bugs, update or add tests before finalizing code. Never leave regressions unresolved.
- Store reusable test fixtures as static files under `resources/tests/` so automated scenarios can rely on consistent inputs.

## Required Local Checks (run before submitting any change)
1. Format and lint:
   - `python -m black .`
   - `python -m ruff check .`
2. Static sanity:
   - `python -m compileall src tests`
3. Tests:
   - `python -m pytest`

Use `python -m pytest -k <pattern>` to focus on a subset of tests when iterating, but always run the full suite before committing.

Address any failures before committing. Document deviations explicitly in commit messages.

## Fallback Notices and Documentation
- When mdview executes without optional dependencies, emit user-facing warnings
  describing the active fallback paths before the process exits.
- Keep `docs/specifications/fallback-behavior.txt` current with sections for
  each supported fallback. Add new entries there whenever additional fallbacks
  are introduced.
- Standing order: extend this section with concise bullets for every new
  fallback so expectations stay visible to contributors.

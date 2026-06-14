<!-- THEKNOWLEDGE_MANAGED_HEADER_START -->
This project uses The Hard Problems Group's specifications and guidance
framework, TheKnowledge. Both AI agents and human developers should reference
`TheKnowledge/AGENTS.md` for detailed instructions.

AI agents must load `TheKnowledge/AGENTS.md` before running automated
tooling that edits, validates, stages, or tests repository files.

Keep only a very small amount of context locked in active memory: that
preflight rule, any live-state override record map, and repo-specific
non-destructive safety limits.

---

Any project-specific `AGENTS.md` content should go below this line and above
the managed TheKnowledge footer.
<!-- THEKNOWLEDGE_MANAGED_HEADER_END -->

## Local TheKnowledge Overrides
- For mdview, mutable project-management records stay under
  `project-management/state/`. That local layout overrides generic
  TheKnowledge consumer examples that mention bare `project-management/*.txt`
  paths.
- Prefer repo-local `scripts/` wrappers and workflow utilities over direct
  `TheKnowledge/scripts` commands when a local script exists. Use
  `python scripts/git_standard_commit_push.py`,
  `python scripts/git_veteran_pull.py`,
  `python scripts/install_git_hooks.py`,
  `python scripts/run_quality_gate_cached.py`,
  `python scripts/report_managed_agents_drift.py`, and
  `python scripts/refresh_managed_agents.py` for mdview-local behavior.
- In a fresh checkout or worktree, initialize the shared guidance submodule
  with `git submodule update --init --recursive TheKnowledge` before using
  managed `AGENTS.md` utilities or relying on shared files from
  `TheKnowledge/`.
- After updating the `TheKnowledge` submodule, run
  `python scripts/report_managed_agents_drift.py`. If it reports drift, run
  `python scripts/refresh_managed_agents.py`, review `git diff`, and stage
  only the intended managed-section changes.

## Ubersight Status
- For substantive multi-step work, keep `.local/ubersight/status.json`
  current with `ubersight --write-status` or compatible JSON so operators can
  monitor long-running autonomous development.
- Update Ubersight status when work begins, at phase boundaries, at slice
  transitions, before long validation or ACP waits, when blocked, and during
  final closeout.
- Source Ubersight phase and slice rows from
  `project-management/development-roadmap.txt`. Create or restore that file
  before relying on Ubersight status if it is missing.
- Keep the visible planning window bounded to the two most recent completed
  entries, the current entry, and up to five future entries. Use
  `project-management/state/phase-slice-stack.txt` as the tracked recovery
  record for that window.
- Do not store prompts, transcripts, credentials, operator-location details,
  WiFi names, Tailnet names, or other sensitive runtime state in Ubersight
  status files or tracked phase and slice records.

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
- Work from `trunk` by default. Do not create or target `VERSIONS/*` or
  other release-line branches unless an operator explicitly reinstates a
  multi-branch maintenance policy.

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
- Before running local checks in a fresh checkout or environment, bootstrap
  the repository-local toolchain from the repository root with
  `./install.sh --mode dev`. That canonical development path provisions the
  configured pyenv bootstrap/runtime selections, writes `.python-version`,
  refreshes `.venv/` inside the checkout, installs mdview through
  `scripts/install_project.py`, and installs repo-local workflow helpers.
  `./bootstrap.sh` and `./scripts/install_prerequisites.sh` remain available
  as compatibility wrappers to `./install.sh`. Interactive development
  installs report whether another `mdview` command appears on PATH before
  prompting whether arbitrary-directory invocations should prefer the
  checkout-local copy. Non-interactive development installs leave PATH
  resolution unchanged by default; set `MDVIEW_DEV_LAUNCHER_MODE=local` or
  `MDVIEW_DEV_LAUNCHER_MODE=system` when automation must force that choice.
  After setup, run local checks with `.venv/bin/python` or an activated
  `.venv`. On Unix-like hosts, the managed development path provisions
  user-scoped pyenv selections and expects `direnv` during development mode.
  Supported Linux flows can install a user-local `direnv` binary
  automatically when needed. Windows users should continue to use the
  platform bootstrap shims under `scripts/windows/`.
- Default to extensive, paranoid, pessimistic unit tests. Cover edge cases,
  error handling, and failure modes alongside happy paths.
- Derive tests from user stories and scenarios; keep them executable and
  reproducible.
- When adding features or fixing bugs, update or add tests before finalizing
  code. Never leave regressions unresolved.
- Store reusable test fixtures as static files under `resources/tests/` so
  automated scenarios can rely on consistent inputs.
- Validate demo Markdown documents through
  `python scripts/run_tool_with_timeout.py demo_check`. The validator keeps a
  per-demo hash cache at `.git/mdview-demo-validation-cache.json` and skips
  unchanged demo files automatically.
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
0. Bootstrap the local environment in a fresh checkout:
   - `./install.sh --mode dev`
1. Format and lint:
   - `python scripts/run_tool_with_timeout.py black`
   - `python scripts/run_tool_with_timeout.py ruff`
2. Static sanity:
   - `python scripts/run_tool_with_timeout.py compileall`
   - `python scripts/run_tool_with_timeout.py entropy_check`
   - `python scripts/run_tool_with_timeout.py entropy_tripwire_verify`
3. Tests:
   - `python scripts/run_tool_with_timeout.py pytest`
   - `python scripts/run_tool_with_timeout.py demo_check`

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
- Invoke `demo_check` through `scripts/run_tool_with_timeout.py` so the
  repository timeout and cache policy stays centralized.
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

<!-- THEKNOWLEDGE_MANAGED_FOOTER_START -->
---

<!-- TheKnowledge-managed footer: place overrides here when the consuming
project needs behavior different from TheKnowledge's own repository setup. -->

## TheKnowledge Overrides
- Use `project-management/backlog.txt` as ordered pending work.
- Keep `project-management/tasks-in-progress.txt` minimal and current.
- Record finished work at the top of
  `project-management/completed-tasks.txt` with ISO 8601 timestamps.
- Track operator actions for AI in `project-management/ai-human-requests.txt`.
- Track proposal records under `project-management/proposals/` using
  `approved/`, `rejected/`, `deferred/`, and `under-review/`.
- Use `project-management/deferred.txt` for explicitly deferred work.
- Queue brief commit-ready summaries in
  `project-management/state/pending-commit-changes.txt`.
- Maintain bug lifecycle summary files under `project-management/bugs/` and
  detailed bug records under `open/`, `in-progress/`, and `closed/`.
- Use `TheKnowledge/standards-and-practices/docs/`
  `AI-backlog-iteration.txt` when told to iterate the backlog.
- Use the consuming project's own `project-management/git-flow.txt` for branch
  and merge operations.
- Treat source documentation as delivery work. Every maintained source file
  should carry top-of-file context, every type and callable should be
  documented, and non-trivial control flow should carry local rationale where
  structure alone would be ambiguous.
- Bootstrap, setup, prerequisite, and environment-selection code should
  follow Python 3.9 best practices unless a higher floor is documented.
- Normal runtime, automation, test, and developer-tooling code should follow
  Python 3.12 best practices unless a component is intentionally constrained.
- Use `./install.sh` when the project is relying on the managed starter
  Python toolchain. The default starter installs `install.sh`,
  `bootstrap.sh`, `scripts/install-stage-2.py`, `bootstrap-stage2.py`,
  `python-environments.json`, `.python-version`, `set-context.sh`,
  `set-context-bootstrap.sh`, `requirements-dev.txt`,
  `scripts/dev_setup.py`, `scripts/python_environment_bootstrap.py`,
  `scripts/tool_validation_profiles.py`, `tool_execution_constraints.json`,
  and `tool_validation_profiles.json`. That flow starts from Python 3.9+,
  defaults to a user-local standard install, supports explicit repo-local
  development mode and venv-only mode, permits system installs only with
  `--system` under root, and requires `direnv` for development mode.
  `bootstrap.sh` and
  `bootstrap-stage2.py` remain compatibility wrappers.
- For substantive development work, prefix intermediary status
  updates with an inline bracketed ISO 8601 timestamp including the
  timezone offset, for example
  `[2026-03-25T01:05:12-07:00] Running full pytest.`
- Use timestamped updates when work begins, before and after
  commands or waits likely to take more than a few seconds, and at
  major phase boundaries.
- Include elapsed durations when they are easy to compute.
- Keep final answers readable; this rule applies to intermediary
  development updates for workflow profiling, not to every sentence
  of casual chat.
- Before any `git add`, list the files about to be staged and ask the
  operator whether to review them.
- Offer these staging-review choices: `1.` review at least one file in the
  changeset, `2.` proceed without review for this changeset, `3.` proceed and
  suppress review prompts for the rest of the current session until the
  operator asks to resume them.
- If review is requested, prefer changeset review in Meld when
  available as the default visual review path.
- Launch `meld .` from the repository or submodule root so Meld opens its
  version-control view for the full working tree.
- If Meld version-control view is unavailable or unsuitable, compare a
  temporary clean snapshot directory against the working tree in Meld's
  folder-comparison mode.
- Otherwise offer file-by-file review in the conversation or abort the
  staging step.
- Never guess a Git author or committer email address from commit history,
  hostnames, remote URLs, network overlays, or similar context.
- Require an explicit commit identity before creating a commit. Prefer
  configured `git` properties such as `user.name` and `user.email`; explicit
  `GIT_COMMITTER_*` and optional separate `GIT_AUTHOR_*` overrides are also
  acceptable when set deliberately.
- When a separate author identity is not explicitly configured, reuse the
  explicit committer identity for author instead of inventing a second
  address.
- Run `git diff` before any `git add` and `git diff --cached` before any
  commit. The standardized commit helper does both automatically.
- Use `python TheKnowledge/scripts/git_standard_commit_push.py -m
  "<subject>"` after the operator has either reviewed the changes or
  explicitly approved proceeding. Pass `--assume-reviewed` only after an
  explicit review decision made outside the helper. Use
  `--resume-review-prompts` to re-enable prompts for the current shell
  session. The helper rejects commits whose author/committer identity is not
  explicitly configured.
- When working primarily in the consuming project and discovering bugs,
  proposals, complaints, or general notes about TheKnowledge itself,
  record them on the TheKnowledge `Feedback` branch.
- When filing that feedback from a consuming project, use the active
  `TheKnowledge/` submodule checkout in that project. Prefer
  `python TheKnowledge/scripts/send_theknowledge_feedback.py prepare`
  and `finish` so the helper captures and restores the submodule state for
  you. Use `--push` only when the configured remote push URL is writable for
  the current operator, and use `abort` when you want to restore the prior
  state without publishing.
- When the active `TheKnowledge/` checkout is read-only for upstream
  maintenance, draft the request first under `ECRs/TheKnowledge/` in the
  consuming project so the handoff stays reviewable before it reaches a
  writable TheKnowledge checkout.
- The `Feedback` branch is only for cross-project feedback flowing back
  into TheKnowledge. Direct maintenance of TheKnowledge itself should keep
  using its normal internal trees on `trunk`.
- Projects may keep proprietary or third-party knacks in the consuming
  project's top-level `knacks/` directory, separate from the stock knacks
  under `TheKnowledge/knacks/`.
- Validate changed knack files with
  `python TheKnowledge/scripts/validate_knacks.py --project-root .`.
- Knack validation should stay lightweight: malformed Markdown and
  high-entropy findings are errors, word-count overruns are warnings, the
  validator uses `.git/knack-validation-cache.json`, and path collisions with
  stock knacks should warn while still evaluating both files.
- When updating the TheKnowledge submodule itself, prefer
  `python TheKnowledge/scripts/update_theknowledge_submodule.py`
  `--project-root . --knowledge-root TheKnowledge`. That helper fetches
  and briefly summarizes the incoming upstream `trunk` delta, adopts the
  reviewed version, runs the drift report, refreshes the managed starter
  files when needed, and leaves a reviewable parent-repo diff.
- For a manual managed-file check without adopting a new upstream commit, run
  `python TheKnowledge/scripts/report_managed_agents_drift.py`
  `--project-root . --knowledge-root TheKnowledge`.
- Follow `tool_execution_constraints.json` when it marks a tool-and-
  environment combination unsafe to parallelize. In a matched Codex sandbox,
  run Black only through
  `python TheKnowledge/scripts/run_tool_with_timeout.py black`; the
  harness will fall back to exactly one file at a time when Black would
  otherwise hit the known multi-file hang. Do not assume `black -W 1` is
  enough. If another file-safe formatter or linter still hangs inside a
  Codex sandbox on a multi-file run, retry the explicit file list one file at
  a time, and rerun the full required checks outside the affected sandbox or
  in CI before clearing the work.
<!-- THEKNOWLEDGE_MANAGED_FOOTER_END -->

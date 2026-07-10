Project State Directory
=======================

Purpose
-------
`project-management/state/` contains dynamic, project-specific working state
that changes frequently during day-to-day execution.

Contents
--------
- `backlog.txt`
- `tasks-in-progress.txt`
- `completed-tasks.txt`
- `deferred.txt`
- `ai-human-requests.txt`
- `pending-commit-changes.txt`
- `bugs/`
- `proposals/`

Boundary
--------
Keep stable process standards and operating procedures outside this directory
(for example, `project-management/git-flow.txt` and top-level `docs/`).
Anything in `state/` is expected to be mutable and project-instance specific.
Keep `pending-commit-changes.txt` brief and commit-body-ready. The standard
commit helper clears it after a successful local commit.

Proposals Directory Layout
==========================

Store proposal files in status-specific subdirectories so queue state is
visible without opening each file.

Status folders
--------------
- `pending/`: New proposals in `Draft` or `Proposed` state.
- `accepted/`: Accepted proposals waiting for implementation.
- `completed/`: Implemented proposals with delivered outcomes.
- `rejected/`: Proposals that were explicitly rejected.
- `superseded/`: Proposals replaced by newer proposals.
- `under-review/`: Debated proposals that must not be auto-implemented
  without explicit operator direction.

Placement rules
---------------
- New proposals start in `pending/` unless an operator directs otherwise.
- Move proposals when status changes; keep file names stable.
- Keep status headers and decision logs updated whenever a move occurs.
- Do not place proposal files directly in `project-management/state/proposals/`.

Bug Reports
===========

Use this directory for detailed per-issue reports that are too long for the
summary log entries in `known-bugs.txt`, `bugs-in-progress.txt`, and
`closed-bugs.txt`.

Structure
---------
- `open/`: reports for confirmed issues that are waiting for work.
- `in-progress/`: reports for issues under active remediation.
- `resolved/`: reports for issues that have been fixed and validated.

State tracking
--------------
The summary status logs remain the canonical queue:
- `known-bugs.txt` for open issues
- `bugs-in-progress.txt` for active remediation
- `closed-bugs.txt` for resolved issues

Store each detailed report in the directory that matches the current summary
status. When the issue changes state, move the report and update the summary
log entry in the corresponding status file.

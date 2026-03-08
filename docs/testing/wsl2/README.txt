Linux Workflow Validation from Windows (WSL2)
=============================================

Purpose
-------
Provide a documented local strategy for running Linux-oriented mdview checks
from Windows development environments through WSL2.

Execution boundary
------------------
Run this workflow only on a real Windows host with WSL2. If you are not on a
real Windows host, treat this material as planning and documentation only.

Planned wrapper entry points
----------------------------
When implemented on Windows, wrappers should provide commands equivalent to:
- PowerShell:
  - `powershell -ExecutionPolicy Bypass -File`
    `scripts/windows/verify-linux-tests-wsl2.ps1`
- cmd.exe:
  - `scripts\\windows\\verify-linux-tests-wsl2.bat`

Planned WSL2 check sequence
---------------------------
Inside WSL2, run checks through timeout wrapper commands:
1. `python scripts/run_tool_with_timeout.py black`
2. `python scripts/run_tool_with_timeout.py ruff`
3. `python scripts/run_tool_with_timeout.py compileall`
4. `python scripts/run_tool_with_timeout.py entropy_check`
5. `python scripts/run_tool_with_timeout.py entropy_tripwire_verify`
6. `python scripts/run_tool_with_timeout.py pytest`

Interpretation
--------------
- PASS: WSL2 checks executed and passed.
- SKIP: host does not provide usable WSL2 for this workflow.
- FAIL: workflow executed and one or more checks failed.

Security guidance
-----------------
- Use least-privilege accounts and avoid unnecessary elevation.
- Prefer a dedicated WSL2 distro/profile for verification if policy allows.
- Do not rely on WSL2 checks as a substitute for CI authority.

Authority boundary
------------------
Linux CI remains the final compatibility gate for Linux behavior. WSL2 local
runs are advisory preflight checks to catch issues earlier on Windows hosts.

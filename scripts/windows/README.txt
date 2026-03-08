Windows Shell Shims
===================

Use these wrappers from Windows 11 command prompts to mirror POSIX workflows
with UTF-8-safe defaults.

Bootstrap environment
---------------------
- PowerShell:
  - `powershell -ExecutionPolicy Bypass -File scripts/windows/bootstrap.ps1`
- cmd.exe:
  - `scripts\\windows\\bootstrap.bat`

Run required checks
-------------------
- PowerShell:
  - `powershell -ExecutionPolicy Bypass -File scripts/windows/run-tool.ps1`
    `black`
  - `powershell -ExecutionPolicy Bypass -File scripts/windows/run-tool.ps1`
    `ruff`
  - `powershell -ExecutionPolicy Bypass -File scripts/windows/run-tool.ps1`
    `compileall`
  - `powershell -ExecutionPolicy Bypass -File scripts/windows/run-tool.ps1`
    `pytest`
- cmd.exe:
  - `scripts\\windows\\run-tool.bat black`
  - `scripts\\windows\\run-tool.bat ruff`
  - `scripts\\windows\\run-tool.bat compileall`
  - `scripts\\windows\\run-tool.bat pytest`

Local isolated emulation (optional)
-----------------------------------
- Use rootless Podman + Wine smoke checks:
  - `scripts/windows/podman-wine-smoke.sh`
- Use host Wine checks with an isolated disposable `WINEPREFIX`:
  - `scripts/windows/host-wine-shim-check.sh`
- Use the orchestrator to run both checks in order and summarize results:
  - `scripts/windows/verify-windows-shims-linux.sh`
- Podman permission-context failures are classified as `SKIP` so host Wine
  fallback can still run.
- The script reports `SKIP` when host policy prevents Wine command execution
  (for example noexec memory-protection restrictions), and reports `FAIL` for
  real shim regressions.
- Windows GitHub Actions remains the authoritative compatibility gate.

Recommended Linux command
-------------------------
- Run through the timeout wrapper so local checks cannot hang:
  - `python scripts/run_tool_with_timeout.py windows_shims_linux`

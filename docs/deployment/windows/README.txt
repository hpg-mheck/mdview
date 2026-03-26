Windows deployment notes
=======================

Provide ``mdview --help`` output alongside packaging artifacts so cmd.exe and
PowerShell users see the same guidance as POSIX environments. Mirror the
shared help text in ``../posix/mdview-help.txt`` and include command examples
for both Windows shells.

Recommended shell shims:
- ``scripts\\windows\\bootstrap.ps1`` and ``bootstrap.bat`` for environment
  setup.
- ``scripts\\windows\\run-tool.ps1`` and ``run-tool.bat`` for timeout-enforced
  checks (black, ruff, compileall, pytest).
- For Linux-hosted development smoke checks of Windows shims, use
  ``python scripts/run_tool_with_timeout.py windows_shims_linux`` and follow
  ``docs/testing/windows/README.txt``.
- For Windows-hosted development checks of Linux workflows through WSL2, use
  the strategy docs in ``docs/testing/wsl2/`` and execute only from a real
  Windows host.

Setup notes:
- Enable long paths in Windows policy/registry before handling deep virtual
  environment paths.
- Prefer ``py -3`` when available; fall back to ``python`` if needed.
- Keep ``PYTHONUTF8=1`` and ``PYTHONIOENCODING=utf-8`` for deterministic text
  handling.

Windows Shim Validation from Linux
==================================

Purpose
-------
Define a safe, repeatable local workflow for checking Windows shell shims
(`.bat` and `.ps1`) while developing on Linux, without depending on external
pagers or privileged host operations.

Scope
-----
- Checks basic interpreter selection and exit-code propagation in Windows
  batch wrappers.
- Uses layered local techniques:
  - rootless Podman + Wine container preflight
  - host Wine fallback check with an isolated disposable `WINEPREFIX`
- Treats Windows GitHub Actions as the authoritative compatibility gate.

Primary command
---------------
- Run the orchestrated Linux workflow through timeout enforcement:
  - `python scripts/run_tool_with_timeout.py windows_shims_linux`

Execution order
---------------
1. `scripts/windows/podman-wine-smoke.sh`
2. `scripts/windows/host-wine-shim-check.sh`

Interpretation
--------------
- `PASS`: at least one local emulation path executed the shim checks
  successfully.
- `SKIP`: no local path could execute (for example host policy or missing Wine
  binaries, or Podman permission-context limits). This is informational, not a
  regression by itself.
- `FAIL`: wrapper behavior regressed or an expected local path errored.

Security model
--------------
- Prefer Podman over Docker when Podman is available.
- Keep Podman rootless on the host.
- Running as root *inside* the disposable container is allowed for isolation
  fidelity and does not imply host privilege escalation.
- Do not attempt host privilege escalation from verification scripts.

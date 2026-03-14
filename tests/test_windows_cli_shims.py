import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _first_non_comment_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


def test_windows_run_tool_shims_set_utf8_and_delegate_to_timeout_wrapper():
    ps1 = _read("scripts/windows/run-tool.ps1")
    bat = _read("scripts/windows/run-tool.bat")

    assert _first_non_comment_line(ps1).startswith("param(")
    assert "PYTHONUTF8" in ps1
    assert "PYTHONIOENCODING" in ps1
    assert "run_tool_with_timeout.py" in ps1
    assert 'Resolve-Path (Join-Path $PSScriptRoot "..\\..")' in ps1
    assert "-Parent -Parent" not in ps1

    assert "PYTHONUTF8" in bat
    assert "PYTHONIOENCODING" in bat
    assert "run_tool_with_timeout.py" in bat
    assert "goto use_py" in bat
    assert "goto use_python" in bat
    assert "exit /b %ERRORLEVEL%" not in bat
    assert 'set "CMD_EXIT=%ERRORLEVEL%"' in bat


def test_windows_bootstrap_shims_delegate_to_install_prerequisites():
    ps1 = _read("scripts/windows/bootstrap.ps1")
    bat = _read("scripts/windows/bootstrap.bat")

    assert _first_non_comment_line(ps1).startswith("param(")
    assert "install_prerequisites.py" in ps1
    assert "PYTHONUTF8" in ps1
    assert "PYTHONIOENCODING" in ps1
    assert 'Resolve-Path (Join-Path $PSScriptRoot "..\\..")' in ps1
    assert "-Parent -Parent" not in ps1

    assert "install_prerequisites.py" in bat
    assert "PYTHONUTF8" in bat
    assert "PYTHONIOENCODING" in bat
    assert "goto use_py" in bat
    assert "goto use_python" in bat
    assert "exit /b %ERRORLEVEL%" not in bat
    assert 'set "CMD_EXIT=%ERRORLEVEL%"' in bat


def test_windows_podman_wine_smoke_script_declares_rootless_podman_flow():
    script = _read("scripts/windows/podman-wine-smoke.sh")

    assert "podman" in script
    assert "podman_run info" in script
    assert '--root "$PODMAN_ROOT"' in script
    assert '--runroot "$PODMAN_RUNROOT"' in script
    assert '--runtime "$OCI_RUNTIME"' in script
    assert "wine cmd /c" in script
    assert "SKIP: Podman unavailable" in script
    assert "SKIP: Wine cmd blocked" in script


def test_windows_linux_orchestrator_wires_container_and_host_checks():
    script = _read("scripts/windows/verify-windows-shims-linux.sh")

    assert "podman-wine-smoke.sh" in script
    assert "host-wine-shim-check.sh" in script
    assert "Step 1/2" in script
    assert "Step 2/2" in script
    assert "local Windows emulation unavailable" in script


def test_timeout_wrapper_config_includes_windows_linux_shim_check():
    config_text = _read("scripts/tool_timeouts.json")
    data = json.loads(config_text)

    tools = data["tools"]
    assert "windows_shims_linux" in tools
    assert tools["windows_shims_linux"]["command"] == [
        "scripts/windows/verify-windows-shims-linux.sh"
    ]

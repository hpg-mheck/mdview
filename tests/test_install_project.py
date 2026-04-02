from __future__ import annotations

from pathlib import Path

import scripts.install_project as installer


class RunRecorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, *, cwd=installer.REPO_ROOT) -> None:
        self.commands.append([str(part) for part in command])


def test_standard_mode_installs_package_and_launcher(
    monkeypatch, tmp_path: Path
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(installer, "run", recorder)

    venv_path = tmp_path / "venv"
    bin_dir = tmp_path / "bin"

    result = installer.main(
        [
            "--mode",
            "standard",
            "--scope",
            "user",
            "--python",
            "/tmp/python",
            "--venv",
            str(venv_path),
            "--bin-dir",
            str(bin_dir),
        ]
    )

    launcher = bin_dir / "mdview"
    assert result == 0
    assert recorder.commands == [
        [
            "/tmp/python",
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            ".[interactive]",
        ]
    ]
    assert installer.STANDARD_LAUNCHER_MARKER in launcher.read_text(encoding="utf-8")


def test_standard_mode_rejects_unmanaged_launcher_with_force_hint(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(installer, "run", recorder)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / "mdview"
    launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    launcher.chmod(0o755)

    result = installer.main(
        [
            "--mode",
            "standard",
            "--scope",
            "user",
            "--python",
            "/tmp/python",
            "--venv",
            str(tmp_path / "venv"),
            "--bin-dir",
            str(bin_dir),
        ]
    )

    assert result == 1
    stderr_lines = capsys.readouterr().err.strip().splitlines()
    assert stderr_lines[-1] == (
        "Use --force if you really want to overwrite your existing "
        f"installed copy at {bin_dir}."
    )


def test_standard_mode_force_overwrites_unmanaged_launcher(
    monkeypatch, tmp_path: Path
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(installer, "run", recorder)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / "mdview"
    launcher.write_text("#!/usr/bin/env bash\necho old\n", encoding="utf-8")
    launcher.chmod(0o755)

    result = installer.main(
        [
            "--mode",
            "standard",
            "--scope",
            "user",
            "--python",
            "/tmp/python",
            "--venv",
            str(tmp_path / "venv"),
            "--bin-dir",
            str(bin_dir),
            "--force",
        ]
    )

    assert result == 0
    assert recorder.commands == [
        [
            "/tmp/python",
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            ".[interactive]",
        ]
    ]
    assert installer.STANDARD_LAUNCHER_MARKER in launcher.read_text(encoding="utf-8")


def test_dev_mode_can_replace_standard_launcher_with_backup(
    monkeypatch, tmp_path: Path
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(installer, "run", recorder)
    monkeypatch.setenv(installer.DEV_LAUNCHER_MODE_ENV, "local")

    venv_path = tmp_path / "venv"
    local_mdview = installer.venv_command_path(venv_path, "mdview")
    local_mdview.parent.mkdir(parents=True)
    local_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    local_mdview.chmod(0o755)

    bin_dir = tmp_path / "bin"
    launcher = bin_dir / "mdview"
    backup = installer.launcher_backup_path(bin_dir)
    installer.write_executable(
        launcher,
        installer.standard_launcher_contents(Path("/tmp/user-standard-mdview")),
    )
    monkeypatch.setenv("PATH", str(bin_dir))

    result = installer.main(
        [
            "--mode",
            "dev",
            "--scope",
            "repo",
            "--python",
            "/tmp/python",
            "--venv",
            str(venv_path),
            "--bin-dir",
            str(bin_dir),
        ]
    )

    assert result == 0
    assert recorder.commands == [
        [
            "/tmp/python",
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "--editable",
            ".[interactive]",
        ]
    ]
    assert installer.DEV_LAUNCHER_MARKER in launcher.read_text(encoding="utf-8")
    assert installer.STANDARD_LAUNCHER_MARKER in backup.read_text(encoding="utf-8")


def test_dev_mode_can_restore_standard_launcher(monkeypatch, tmp_path: Path) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(installer, "run", recorder)
    monkeypatch.setenv(installer.DEV_LAUNCHER_MODE_ENV, "system")

    venv_path = tmp_path / "venv"
    local_mdview = installer.venv_command_path(venv_path, "mdview")
    local_mdview.parent.mkdir(parents=True)
    local_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    local_mdview.chmod(0o755)

    bin_dir = tmp_path / "bin"
    launcher = bin_dir / "mdview"
    backup = installer.launcher_backup_path(bin_dir)
    installer.write_executable(launcher, installer.dev_launcher_contents(local_mdview))
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(
        installer.standard_launcher_contents(Path("/tmp/user-standard-mdview")),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(bin_dir))

    result = installer.main(
        [
            "--mode",
            "dev",
            "--scope",
            "repo",
            "--python",
            "/tmp/python",
            "--venv",
            str(venv_path),
            "--bin-dir",
            str(bin_dir),
        ]
    )

    assert result == 0
    assert recorder.commands == [
        [
            "/tmp/python",
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "--editable",
            ".[interactive]",
        ]
    ]
    assert installer.STANDARD_LAUNCHER_MARKER in launcher.read_text(encoding="utf-8")
    assert not backup.exists()


def test_venv_only_mode_skips_project_install(monkeypatch, tmp_path: Path) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(installer, "run", recorder)

    result = installer.main(
        [
            "--mode",
            "venv-only",
            "--scope",
            "repo",
            "--python",
            "/tmp/python",
            "--venv",
            str(tmp_path / "venv"),
            "--bin-dir",
            str(tmp_path / "bin"),
        ]
    )

    assert result == 0
    assert recorder.commands == []

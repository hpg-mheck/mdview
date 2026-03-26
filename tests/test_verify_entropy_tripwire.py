from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "dev-utils" / "security" / "verify_entropy_tripwire.py"


def _token() -> str:
    return "".join(
        [
            "X4b9Rk2Q",
            "m8Lp0Vz7",
            "Hn6Tw3Ys",
            "5Df1Ja9C",
            "u2Me7Po4",
            "Gi8Nr5Kb",
            "1Qx6Zv0",
        ]
    )


def _run_tripwire(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def _sentinel_fixture() -> str:
    return "\n".join(
        [
            "# baseline: repeated words repeated words repeated words repeated words",
            'normal_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            'normal_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
            f'high_line = "{_token()}"',
            "",
        ]
    )


def test_tripwire_verifier_passes_for_clean_repo_with_sentinel(tmp_path: Path) -> None:
    tripwire = tmp_path / "tests" / "test_entropy_check.py"
    tripwire.parent.mkdir(parents=True)
    tripwire.write_text(_sentinel_fixture(), encoding="utf-8")
    (tmp_path / "README.txt").write_text(
        "normal text line one\nnormal text line two\n", encoding="utf-8"
    )

    result = _run_tripwire(tmp_path)

    assert result.returncode == 0
    assert "PASS: tripwire verification complete." in result.stdout


def test_tripwire_verifier_ignores_repo_local_codex_state_and_package_lock(
    tmp_path: Path,
) -> None:
    tripwire = tmp_path / "tests" / "test_entropy_check.py"
    tripwire.parent.mkdir(parents=True)
    tripwire.write_text(_sentinel_fixture(), encoding="utf-8")
    auth = tmp_path / ".codex-home" / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(
        "\n".join(
            [
                "{",
                f'  "access_token": "{_token()}"',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    package_lock = tmp_path / ".codex-local" / "package-lock.json"
    package_lock.parent.mkdir(parents=True)
    package_lock.write_text(
        "\n".join(
            [
                "{",
                f'  "integrity": "{_token()}"',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    root_package_lock = tmp_path / "package-lock.json"
    root_package_lock.write_text(
        "\n".join(
            [
                "{",
                '  "name": "mdview-web-shims",',
                f'  "integrity": "{_token()}"',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_tripwire(tmp_path)

    assert result.returncode == 0
    assert "PASS: tripwire verification complete." in result.stdout


def test_tripwire_verifier_fails_when_non_sentinel_finding_exists(
    tmp_path: Path,
) -> None:
    tripwire = tmp_path / "tests" / "test_entropy_check.py"
    tripwire.parent.mkdir(parents=True)
    tripwire.write_text(_sentinel_fixture(), encoding="utf-8")
    (tmp_path / "secretish.txt").write_text(
        "\n".join(
            [
                "ordinary prose for baseline stabilization",
                "another ordinary prose line for baseline",
                _token(),
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_tripwire(tmp_path)

    assert result.returncode == 1
    assert "Entropy harness reported non-sentinel findings." in result.stderr

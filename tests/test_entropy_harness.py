from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "dev-utils" / "security" / "run_entropy_harness.py"


def _run_harness(target: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARNESS), *extra_args, str(target)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_harness_ignores_intentional_entropy_test_fixture(tmp_path: Path) -> None:
    token = "".join(
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
    test_file = tmp_path / "tests" / "test_entropy_check.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "\n".join(
            [
                f'high_line = "{token}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_harness(tmp_path)

    assert result.returncode == 0
    assert "flagged 0 files" in result.stdout


def test_harness_excludes_package_lock_and_node_modules_by_default(
    tmp_path: Path,
) -> None:
    token = "".join(
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
    package_lock = tmp_path / "package-lock.json"
    package_lock.write_text(
        "\n".join(
            [
                "{",
                f'  "integrity": "{token}"',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    nested_lock = tmp_path / "node_modules" / ".package-lock.json"
    nested_lock.parent.mkdir(parents=True)
    nested_lock.write_text(
        "\n".join(
            [
                "{",
                f'  "integrity": "{token}"',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_harness(tmp_path)

    assert result.returncode == 0
    assert "flagged 0 files" in result.stdout


def test_harness_flags_unexcluded_high_entropy_line(tmp_path: Path) -> None:
    token = "".join(
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
    suspect = tmp_path / "suspect.txt"
    suspect.write_text(
        "\n".join(
            [
                "this is normal prose line with repeated words.",
                "another normal prose line for baseline formation.",
                token,
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_harness(suspect)

    assert result.returncode == 1
    assert "flagged 1 files" in result.stdout


def test_timeout_wrapper_config_includes_entropy_harness() -> None:
    config_path = ROOT / "scripts" / "tool_timeouts.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))

    tool = data["tools"]["entropy_check"]
    assert tool["command"] == ["python", "dev-utils/security/run_entropy_harness.py"]

    verifier = data["tools"]["entropy_tripwire_verify"]
    assert verifier["command"] == [
        "python",
        "dev-utils/security/verify_entropy_tripwire.py",
    ]


def test_harness_supports_json_output_passthrough(tmp_path: Path) -> None:
    sample = tmp_path / "normal.txt"
    sample.write_text(
        "\n".join(
            [
                "plain line one with repeated prose content for stable baseline.",
                "plain line two with repeated prose content for stable baseline.",
                "plain line three with repeated prose content for stable baseline.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_harness(sample, "--json-output")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1.0.0"
    assert payload["summary"]["reported_high_entropy_lines"] == 0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "dev-utils" / "security" / "entropy-check.py"


def _run_entropy_check(
    target: Path, *extra_args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra_args, str(target)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_entropy_check_flags_high_entropy_spike(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    low_lines = [
        "this is ordinary prose content with predictable words and spacing.",
        "documentation text usually has repeated structures and lower entropy.",
        "another normal line that should be part of the clipped baseline set.",
    ]
    high_line = "X4b9Rk2Qm8Lp0Vz7Hn6Tw3Ys5Df1Ja9Cu2Me7Po4Gi8Nr5Kb1Qx6Zv0"
    sample.write_text("\n".join(low_lines + [high_line]) + "\n", encoding="utf-8")

    result = _run_entropy_check(sample)

    assert result.returncode == 1
    assert "flagged 1 files" in result.stdout
    assert "reported 1 high-entropy lines" in result.stdout
    assert "L4" in result.stdout


def test_entropy_check_returns_zero_when_no_spikes(tmp_path: Path) -> None:
    sample = tmp_path / "normal.txt"
    lines = [
        "plain documentation line with repeated terms and clear prose.",
        "another plain line that should not trigger secret-like detection.",
        "more prose to make the baseline stable across the small fixture.",
        "final plain line with no random-looking token material present.",
    ]
    sample.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _run_entropy_check(sample)

    assert result.returncode == 0
    assert "flagged 0 files" in result.stdout
    assert "reported 0 high-entropy lines" in result.stdout


def test_entropy_check_json_output_has_schema_version_first(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
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
    sample.write_text(
        "\n".join(
            [
                "plain baseline text with repeated words and predictable structure.",
                "another plain baseline line to stabilize relative entropy.",
                token,
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_entropy_check(sample, "--json-output")

    assert result.returncode == 1
    stripped = result.stdout.lstrip()
    assert stripped.startswith('{\n  "schema_version": ')

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1.0.0"
    assert payload["summary"]["flagged_files"] == 1
    assert payload["summary"]["reported_high_entropy_lines"] >= 1

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_quality_gate_cached.py"


def _run_cached(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def _make_fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    (repo / "dev-utils").mkdir(parents=True)
    (repo / "resources").mkdir(parents=True)

    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_ok():\n    assert 1\n", encoding="utf-8"
    )
    (repo / "resources" / "fixture.txt").write_text("fixture\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.black]\nline-length = 88\n", encoding="utf-8"
    )

    stub = repo / "scripts" / "run_tool_with_timeout.py"
    stub.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import pathlib",
                "import sys",
                "log = pathlib.Path('.git/quality-gate-calls.log')",
                "log.parent.mkdir(parents=True, exist_ok=True)",
                "with log.open('a', encoding='utf-8') as handle:",
                "    handle.write(sys.argv[1] + '\\n')",
                "raise SystemExit(0)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return repo


def _read_calls(repo_root: Path) -> list[str]:
    log = repo_root / ".git" / "quality-gate-calls.log"
    if not log.exists():
        return []
    return [
        line.strip()
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_quality_gate_cache_skips_when_inputs_unchanged(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)

    first = _run_cached(repo, "--checks", "black", "entropy_tripwire_verify")
    assert first.returncode == 0
    assert "RUN black: cache miss" in first.stdout
    assert "RUN entropy_tripwire_verify: cache miss" in first.stdout

    second = _run_cached(repo, "--checks", "black", "entropy_tripwire_verify")
    assert second.returncode == 0
    assert "SKIP black: cache hit" in second.stdout
    assert "SKIP entropy_tripwire_verify: cache hit" in second.stdout

    calls = _read_calls(repo)
    assert calls == ["black", "entropy_tripwire_verify"]

    cache = json.loads(
        (repo / ".git" / "mdview-quality-cache.json").read_text(encoding="utf-8")
    )
    assert cache["schema_version"] == "1.0.0"
    assert cache["checks"]["black"]["status"] == "pass"


def test_quality_gate_cache_invalidates_when_inputs_change(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)

    first = _run_cached(repo, "--checks", "black")
    assert first.returncode == 0

    (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    second = _run_cached(repo, "--checks", "black")
    assert second.returncode == 0
    assert "RUN black: cache miss" in second.stdout

    calls = _read_calls(repo)
    assert calls == ["black", "black"]


def test_quality_gate_cache_ignores_repo_local_codex_state(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    auth = repo / ".codex-home" / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text('{"access_token": "token-one"}\n', encoding="utf-8")
    package_lock = repo / ".codex-local" / "package-lock.json"
    package_lock.parent.mkdir(parents=True)
    package_lock.write_text('{"integrity": "token-one"}\n', encoding="utf-8")

    first = _run_cached(repo, "--checks", "entropy_tripwire_verify")
    assert first.returncode == 0
    assert "RUN entropy_tripwire_verify: cache miss" in first.stdout

    auth.write_text('{"access_token": "token-two"}\n', encoding="utf-8")
    package_lock.write_text('{"integrity": "token-two"}\n', encoding="utf-8")
    second = _run_cached(repo, "--checks", "entropy_tripwire_verify")
    assert second.returncode == 0
    assert "SKIP entropy_tripwire_verify: cache hit" in second.stdout

    calls = _read_calls(repo)
    assert calls == ["entropy_tripwire_verify"]

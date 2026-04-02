from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "install_stage_2",
    ROOT / "scripts" / "install-stage-2.py",
)
assert SPEC is not None and SPEC.loader is not None
INSTALL_STAGE_2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL_STAGE_2)


def test_suppress_child_failure_summary_for_install_project() -> None:
    error = subprocess.CalledProcessError(
        1,
        ["/tmp/python", str(ROOT / "scripts" / "install_project.py")],
    )

    assert INSTALL_STAGE_2.suppress_child_failure_summary(error) is True


def test_suppress_child_failure_summary_for_other_failures() -> None:
    error = subprocess.CalledProcessError(
        1,
        ["/tmp/python", "-m", "pip", "install", "."],
    )

    assert INSTALL_STAGE_2.suppress_child_failure_summary(error) is False

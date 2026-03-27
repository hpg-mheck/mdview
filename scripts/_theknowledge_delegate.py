from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
THEKNOWLEDGE_ROOT = REPO_ROOT / "TheKnowledge"
THEKNOWLEDGE_SCRIPTS_ROOT = THEKNOWLEDGE_ROOT / "scripts"


def load_script_module(script_name: str) -> ModuleType:
    script_path = THEKNOWLEDGE_SCRIPTS_ROOT / script_name
    if not script_path.is_file():
        raise RuntimeError(f"Missing TheKnowledge script: {script_path}")

    module_name = f"_theknowledge_{script_name.replace('-', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module from {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def reexport_public(module: ModuleType, namespace: dict[str, object]) -> None:
    for name, value in module.__dict__.items():
        if name.startswith("__"):
            continue
        namespace.setdefault(name, value)

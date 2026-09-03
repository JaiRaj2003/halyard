import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO_ROOT / "analysis" / "audit"
sys.path.insert(0, str(AUDIT_DIR))
sys.path.insert(0, str(REPO_ROOT))


def load_step(filename: str) -> ModuleType:
    """Import a numbered audit step, whose name is not a valid module name."""
    path = AUDIT_DIR / filename
    spec = importlib.util.spec_from_file_location(f"step_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

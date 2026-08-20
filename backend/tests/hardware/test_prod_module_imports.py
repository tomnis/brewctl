"""
Static check on the modules that only production ever imports.

`LunarScale` and `MotorKitValve` are imported lazily inside `create_scale()` /
`create_valve()` behind `BREWCTL_IS_PROD`, and they pull in `pyacaia` / `bluepy` /
Adafruit, which do not install off the Pi. So nothing in the suite imports them,
and a broken import in one of them survives a fully green test run and only
surfaces as a crash-looping systemd unit on the Pi.

That happened: `LunarScale` imported the scale reconnect settings from
`hardware.config`, where they have never been defined -- they live in
`core.config`. `install.sh`'s import check does not catch it either, since it only
imports the third-party libraries.

These tests parse the modules instead of importing them, so they need none of the
device libraries. They resolve each `from ..x import a, b` against the real target
module and assert the names exist.
"""

import ast
import importlib
from pathlib import Path

import pytest

HARDWARE_DIR = Path(__file__).resolve().parents[2] / "src" / "brewctl" / "hardware"

# The modules that are only ever imported on the Pi.
PROD_ONLY_MODULES = ["LunarScale.py", "MotorKitValve.py"]


def _resolve(module_path: Path, node: ast.ImportFrom) -> str | None:
    """Turn a relative `from ..core.config import X` into `brewctl.core.config`."""
    if not node.level:
        return node.module if (node.module or "").startswith("brewctl") else None
    # level 1 = the containing package (brewctl.hardware), 2 = its parent, ...
    parts = ["brewctl", "hardware"][: len(["brewctl", "hardware"]) - (node.level - 1)]
    return ".".join(parts + ([node.module] if node.module else []))


def _import_from_nodes(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    return [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]


@pytest.mark.parametrize("filename", PROD_ONLY_MODULES)
def test_prod_module_exists(filename):
    assert (HARDWARE_DIR / filename).is_file(), f"{filename} moved -- update this test"


@pytest.mark.parametrize("filename", PROD_ONLY_MODULES)
def test_internal_imports_resolve(filename):
    """Every name imported from another brewctl module must actually be there."""
    path = HARDWARE_DIR / filename

    for node in _import_from_nodes(path):
        target = _resolve(path, node)
        if target is None:
            continue  # third-party (pyacaia, adafruit) -- not installable here

        try:
            mod = importlib.import_module(target)
        except ImportError as e:  # pragma: no cover - only on a genuinely broken tree
            pytest.fail(f"{filename} imports from {target}, which does not import: {e}")

        for alias in node.names:
            if alias.name == "*":
                continue
            assert hasattr(mod, alias.name), (
                f"{filename} does `from {target} import {alias.name}`, "
                f"but {target} has no such name"
            )

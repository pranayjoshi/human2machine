"""Put the service package ahead of this test directory on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_UNIT = Path(__file__).resolve().parent.parent
_SERVICE = _ROOT / "services" / "fusion-runtime"

if str(_UNIT) in sys.path:
    sys.path.remove(str(_UNIT))
for _path in (
    _ROOT / "packages" / "contracts-python" / "src",
    _ROOT / "packages" / "runtime-python" / "src",
    _SERVICE,
):
    sys.path.insert(0, str(_path))

for _name in list(sys.modules):
    if _name != "fusion_runtime" and not _name.startswith("fusion_runtime."):
        continue
    _mod = sys.modules[_name]
    _origin = getattr(_mod, "__file__", None) or ""
    _paths = list(getattr(_mod, "__path__", []))
    _looks_like_tests = "tests/unit/fusion_runtime" in _origin.replace("\\", "/") or any(
        "tests/unit/fusion_runtime" in path.replace("\\", "/") for path in _paths
    )
    if _looks_like_tests or getattr(_mod, "__file__", None) is None:
        del sys.modules[_name]

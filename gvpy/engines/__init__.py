"""
Layout engine registry — discover and instantiate layout engines.

All layout engines live under ``gvpy.engines.<name>/`` and are registered
here for dispatch by the CLI (``gvcli.py``) and programmatic use.

Usage::

    from gvpy.engines import get_engine, list_engines

    EngineClass = get_engine("dot")
    result = EngineClass(graph).layout()

    for name, info in list_engines().items():
        print(f"{name}: {info['status']}")
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LayoutEngine

# Registry: engine name → (module_path, class_name, status)
_ENGINES: dict[str, tuple[str, str, str]] = {
    "dot":       ("gvpy.engines.dot",       "DotLayout",       "implemented"),
    "circo":     ("gvpy.engines.circo",     "CircoLayout",     "implemented"),
    "neato":     ("gvpy.engines.neato",     "NeatoLayout",     "implemented"),
    "fdp":       ("gvpy.engines.fdp",       "FdpLayout",       "implemented"),
    "sfdp":      ("gvpy.engines.sfdp",      "SfdpLayout",      "implemented"),
    "twopi":     ("gvpy.engines.twopi",     "TwopiLayout",     "implemented"),
    "osage":     ("gvpy.engines.osage",     "OsageLayout",     "implemented"),
    "patchwork": ("gvpy.engines.patchwork", "PatchworkLayout", "implemented"),
    # mingle moved to gvpy.tools.mingle (it's a post-processor, not a layout engine)
}


def get_engine(name: str) -> type["LayoutEngine"]:
    """Import and return a layout engine class by name.

    Raises ``KeyError`` if the engine name is unknown.
    """
    if name not in _ENGINES:
        available = ", ".join(sorted(_ENGINES))
        raise KeyError(f"Unknown layout engine '{name}'. Available: {available}")
    mod_path, cls_name, _ = _ENGINES[name]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


def list_engines() -> dict[str, dict[str, str]]:
    """Return a dict of engine name → {module, class, status}."""
    return {
        name: {"module": mod, "class": cls, "status": status}
        for name, (mod, cls, status) in _ENGINES.items()
    }


def register_engine(name: str, module_path: str, class_name: str,
                     status: str = "implemented"):
    """Register a custom layout engine at runtime."""
    _ENGINES[name] = (module_path, class_name, status)

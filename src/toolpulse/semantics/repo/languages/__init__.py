from __future__ import annotations
import importlib

_KNOWN = ("python", "cpp", "java")

def get_language(name: str):
    if name not in _KNOWN:
        raise ValueError(f"unknown language {name!r}; known: {', '.join(_KNOWN)}")
    return importlib.import_module(f"{__name__}.{name}")

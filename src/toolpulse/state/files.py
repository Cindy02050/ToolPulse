# src/toolpulse/state/files.py
"""Read/edit file tracking (single home of mutable file state, design D6).

`_normalize_path` and `_paths_match` are verbatim ports of the legacy helpers in
SWE-agent/sweagent/agent/algorithm/utils/action_semantic.py:130-144; the legacy
module-level globals `_EDITED_FILES`/`_READ_FILES` become instance state here.
"""
from __future__ import annotations

import posixpath


def _normalize_path(path: str) -> str:
    return posixpath.normpath(path)


def _paths_match(read_path: str, target_path: str) -> bool:
    if read_path == target_path:
        return True
    if not target_path.startswith("/"):
        return read_path.endswith("/" + target_path) or read_path == target_path
    return False


class FileStateTracker:
    """Tracks which files were read vs edited; satisfies core.protocols.FileTracker."""

    def __init__(self) -> None:
        self.edited: set[str] = set()
        self.read: set[str] = set()

    def record_read(self, path: str) -> None:
        self.read.add(_normalize_path(path))

    def record_edit(self, path: str) -> None:
        self.edited.add(_normalize_path(path))

    def has_read(self, path: str) -> bool:
        """Port of legacy _has_read_file: exact or suffix match (relative targets)."""
        target = _normalize_path(path)
        return any(_paths_match(read_path, target) for read_path in self.read)

    def has_edited(self, path: str) -> bool:
        return _normalize_path(path) in self.edited

    def snapshot(self) -> dict:
        return {"edited": sorted(self.edited), "read": sorted(self.read)}

    def restore(self, data: dict) -> None:
        self.edited.clear()
        self.read.clear()
        self.edited.update(data.get("edited", ()))
        self.read.update(data.get("read", ()))

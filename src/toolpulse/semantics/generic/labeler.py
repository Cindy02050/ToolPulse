# src/toolpulse/semantics/generic/labeler.py
"""Framework-neutral default labeler (design D16/D19).

Maps each tool through an explicit ``tool -> LabelKind`` table; unknown
tools fall back to ``LabelKind.OTHER`` labeled with the tool name (or
``"G"`` for empty actions). Intentionally no error classification and no
file flags: ``error`` stays none and ``is_patch``/``is_create``/
``is_read`` stay False, so failed/blind detection that keys on them is
inert under this labeler by design (D16). ``state`` and ``record`` are
accepted only for ``core.protocols.ActionLabeler`` conformance — the
labeler is side-effect free and never touches ``state.files`` (D19).
"""

from __future__ import annotations

from typing import Mapping

from toolpulse.core.types import LabelInfo, LabelKind


class GenericLabeler:
    """Neutral ``ActionLabeler``: tool-name labels, zero side effects."""

    def __init__(self, tool_kinds: Mapping[str, LabelKind] | None = None) -> None:
        self._tool_kinds = dict(tool_kinds) if tool_kinds else {}

    def label(self, action, step, state, *, record):
        tool = action.tool or ""
        kind = self._tool_kinds.get(tool, LabelKind.OTHER)
        return LabelInfo(label=tool or "G", kind=kind)

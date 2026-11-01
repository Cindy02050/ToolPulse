# src/toolpulse/semantics/repo/labeler.py
"""SWE-repo 13-label taxonomy — one ``ActionLabeler`` implementation.

Port of legacy ``sweagent/agent/algorithm/utils/action_semantic.py``.

Adaptations vs legacy (behaviour-preserving except where marked):

- every action-dict read became an attribute read (``action.get("tool")`` →
  ``action.tool`` etc.); ``args`` stays ``action.args`` (dict or str).
- the observation moved off the action dict onto ``StepObservation``;
  ``label()`` reads ``step.observation`` (the legacy label entry point read
  ``action.get("observation")``).
- the local ``_strip_timeout_wrapper`` is gone: ``_classify_bash_command``
  calls the canonical ``toolpulse.parsing.shell.strip_timeout_wrapper``.
- the java/cpp branches resolve their packs through the Task 9 registry
  ``toolpulse.semantics.repo.languages.get_language`` instead of importing
  ``lang_cpp``/``lang_java`` at module top.
- the module-level ``_EDITED_FILES`` global is gone: re-patch detection
  reads ``state.files.has_edited(target)`` and post-execution labels call
  ``state.files.record_edit(target)`` (FileStateTracker owns the sets).
  Read recording is NOT done here — per D19 the detector records reads
  from ``LabelInfo.is_read`` at analyze time.
- **D13 (intentional divergence)**: former SKIP actions (``cd``,
  ``rm``/``mkdir``/``mv``/``cp``/``touch``/``chmod``/``ln``, empty tool)
  now get the refined label ``"G"`` (kind OTHER) and enter the sequence;
  ``_enrich_label`` maps base phase ``"SKIP"`` to ``"G"`` where legacy
  returned ``"SKIP"`` (dropped by the legacy caller).
- NOT ported: ``_EDITED_FILES``/``_READ_FILES`` globals,
  ``reset_action_semantic_state``, ``record_read_file``,
  ``is_blind_patch_action``, ``action_target_file``, ``_has_read_file``
  (superseded by ``state.files`` and the ``LabelInfo`` fields) and the
  ``_normalize_path``/``_paths_match`` copies (no ported code path calls
  them; ``state/files.py`` owns the canonical copies).
"""

from __future__ import annotations

import re
import shlex

from toolpulse.core.types import Action, ActionError, LabelInfo, LabelKind
from toolpulse.core.types import SEMANTIC_LABEL_DISPLAY, semantic_pattern_display   # moved to core (2026-10-31); re-exported for backward compat
from toolpulse.parsing.shell import strip_timeout_wrapper
from toolpulse.semantics.repo.errors import (
    action_error_type,
    observation_error_fingerprint,
)
from toolpulse.semantics.repo.languages import get_language

ENV_COMMANDS = {
    "pip",
    "apt-get",
    "apt",
    "conda",
    "make",
    "export",
    "source",
    "sphinx-build",
    "sphinx-quickstart",
    "tox",
    "cython",
    "cythonize",
}
PYTHON_COMMANDS = {
    "python",
    "python2",
    "python3",
    "python3.6",
    "python3.7",
    "python3.8",
}
VR_PATTERN = re.compile(r"reproduce_|repro_|test_repro|bug_|debug_", re.IGNORECASE)
READ_FILE_LABELS = {"Lt", "Lb"}
PATCH_LABELS = {"P", "Ps", "Pi", "Pr"}

# SEMANTIC_LABEL_DISPLAY and semantic_pattern_display moved to core/types.py
# (shared label contract, 2026-10-31 final review revision); re-exported above for backward
# compatibility — existing ``from ...repo.labeler import semantic_pattern_display``
# callers keep working.

KIND_OF_LABEL: dict[str, LabelKind] = {
    "Ls": LabelKind.RETRIEVE,
    "Lt": LabelKind.RETRIEVE,
    "Lb": LabelKind.RETRIEVE,
    "E": LabelKind.OPERATE,
    "P": LabelKind.OPERATE,
    "Ps": LabelKind.OPERATE,
    "Pi": LabelKind.OPERATE,
    "Pr": LabelKind.OPERATE,
    "Vp": LabelKind.COMPUTE,
    "Vf": LabelKind.COMPUTE,
    "Ve": LabelKind.COMPUTE,
    "G": LabelKind.OTHER,
    "Emp": LabelKind.OTHER,
}


class RepoLabeler:
    """Labels actions with the SWE-repo 13-label taxonomy.

    Satisfies ``core.protocols.ActionLabeler``. ``record=True`` labels are
    post-execution and record patch targets into ``state.files``;
    ``record=False`` labels are read-only pre-execution inspections.
    """

    def __init__(self, language: str = "python") -> None:
        get_language(language)   # resolve/validate the language pack up front
        self._language = language

    def label(self, action, step, state, *, record):
        raw = action.raw_action
        if isinstance(raw, str) and not raw.strip():
            return LabelInfo(label="Emp", kind=LabelKind.OTHER)
        base_phase, action_type = _classify_action(action, self._language)
        adjusted_error = _action_error_type(action, step.observation, self._language)
        target = _target_file(action, self._language)
        is_create = _is_create_action(action)
        is_patch = base_phase == "P"
        is_repatch = is_patch and target is not None and state.files.has_edited(target)
        if record and is_patch and target:
            state.files.record_edit(target)
        label = _enrich_label(base_phase, action_type, adjusted_error, is_repatch)
        fingerprint = (observation_error_fingerprint(step.observation, adjusted_error)
                       if adjusted_error != "none" else None)
        return LabelInfo(
            label=label, kind=KIND_OF_LABEL[label], target_file=target,
            is_patch=is_patch, is_create=is_create,
            is_read=label in READ_FILE_LABELS or is_create,   # D19
            error=ActionError(kind=adjusted_error, fingerprint=fingerprint),
        )


def _is_create_action(action: Action) -> bool:
    tool = str(action.tool or "")
    if tool == "create":
        return True

    args = action.args
    return tool == "str_replace_editor" and isinstance(args, dict) and args.get("command") == "create"


def _action_error_type(action: Action, observation: str, language: str = "python") -> str:
    observation = str(observation or "")
    filtered_observation = "\n".join(
        re.sub(r"\berror:", "error :", line, flags=re.IGNORECASE)
        if re.search(r"\bexpected\b", line, re.IGNORECASE)
        else line
        for line in observation.splitlines()
    )
    error_type = action_error_type(action, filtered_observation, language=language)

    if re.search(r"timed out|timeout|took more than \d+ seconds|was cancelled", observation, re.IGNORECASE):
        return error_type
    if error_type in {"syntax", "import"}:
        return error_type
    if re.search(
        r"(?im)^\s*\S*python(?:\d+(?:\.\d+)*)?:\s+No module named\s+\S+",
        observation,
    ):
        return "import"
    return error_type


def _classify_action(action: Action, language: str = "python") -> tuple[str, str]:
    tool = str(action.tool or "")
    args = action.args

    if not tool:
        return ("SKIP", "empty")

    if tool == "str_replace_editor":
        command = str(args.get("command", "view")) if isinstance(args, dict) else "view"
        has_view_range = bool(args.get("view_range")) if isinstance(args, dict) else False
        return _classify_editor(command, has_view_range)

    if tool == "open":
        return ("L", "read_file")
    if tool == "goto":
        return ("L", "read_targeted")
    if tool in {"scroll_down", "scroll_up"}:
        return ("L", "navigate_file")
    if tool == "edit":
        return ("P", "edit")
    if tool == "create":
        return ("P", "create")
    if tool == "search_file":
        return ("L", "search_precise")
    if tool in {"search_dir", "find_file"}:
        return ("L", "search_broad")
    if tool.startswith("bash-"):
        return _classify_bash_command(
            str(args or ""),
            language,
            raw_action=str(action.raw_action or ""),
        )

    return ("G", "other")


def _target_file(action: Action, language: str = "python") -> str | None:
    args = action.args
    if isinstance(args, dict):
        path = args.get("path")
        return str(path) if path else None
    if language == "cpp":
        return get_language(language).extract_patch_target(str(action.raw_action or ""))
    return None


def _classify_editor(command: str, has_view_range: bool) -> tuple[str, str]:
    if command == "view":
        return ("L", "read_targeted" if has_view_range else "read_file")
    if command == "create":
        return ("P", "create")
    if command in {"str_replace", "insert", "undo_edit"}:
        return ("P", "edit")
    return ("L", "read_file")


def _classify_bash_command(
    command: str,
    language: str = "python",
    *,
    raw_action: str = "",
) -> tuple[str, str]:
    command = command.strip()
    if not command:
        return ("G", "other")

    command = strip_timeout_wrapper(command)
    if language == "java":
        adapted = get_language(language).classify_bash_command(command)
        if adapted is not None:
            return adapted
    elif language == "cpp":
        adapted = get_language(language).classify_bash_command(raw_action or command)
        if adapted is not None:
            return adapted
    first_word = command.split()[0] if command else ""
    command_lower = command.lower()

    if first_word in PYTHON_COMMANDS:
        if re.search(r"--help\b|-h\b", command):
            return ("G", "other")
        if "--version" in command:
            return ("E", "environment")

        body = _extract_python_c_body(command)
        if body:
            body_lower = body.lower()
            if any(keyword in body_lower for keyword in ("version", "__version__", "sys.version")):
                return ("E", "environment")

            has_code_definition = bool(re.search(r"^\s*(?:class|(?:async\s+)?def)\s+\w+", body, re.MULTILINE))
            if (
                re.match(r"^[\"']?\s*import\s+\w", body)
                and "assert" not in body_lower
                and "test" not in body_lower
                and not has_code_definition
            ):
                return ("E", "environment")
            if _is_inline_reproduction(body):
                return ("V", "reproduce")

        if "pytest" in command:
            return ("V", "run_tests")
        if VR_PATTERN.search(command):
            return ("V", "reproduce")
        return ("V", "run_code")

    if first_word == "pytest":
        return ("V", "run_tests")
    if first_word in {"sed", "awk"}:
        if first_word == "sed" and re.search(r"-n\s+'?\d", command):
            return ("L", "read_targeted")
        return ("P", "edit")
    if re.search(r"(>>|>\s)", command) and any(token in command_lower for token in ("cat ", "echo ", "printf ")):
        return ("P", "edit")
    if first_word in {"grep", "rg"}:
        return ("L", "search_precise")
    if first_word == "find":
        return ("L", "search_broad")
    if first_word in {"head", "tail"}:
        return ("L", "read_targeted")
    if first_word in {"cat", "less", "ls"}:
        return ("L", "read_file")
    if first_word in ENV_COMMANDS:
        return ("E", "environment")
    if any(token in command_lower for token in ("pip ", "apt ", "conda ", "apt-get ")):
        return ("E", "environment")
    if first_word == "cd":
        return ("SKIP", "navigate_dir")
    if first_word in {"rm", "mkdir", "mv", "cp", "touch", "chmod", "ln"}:
        return ("SKIP", "file_mgmt")
    if first_word == "submit":
        return ("G", "submit")
    if first_word in {"exit_cost", "exit_format"}:
        return ("G", "give_up")
    if first_word.startswith(("DJANGO_SETTINGS", "PYTHONPATH", "./")):
        return ("V", "run_code")
    return ("G", "other")


def _enrich_label(base_phase: str, action_type: str, error_type: str, is_repatch: bool) -> str:
    if base_phase == "SKIP":
        return "G"   # D13: former-SKIP actions enter the sequence as "G"/OTHER (legacy returned "SKIP")
    if base_phase == "L":
        if action_type in {"search_precise", "search_broad"}:
            return "Ls"
        if action_type == "read_targeted":
            return "Lt"
        return "Lb"
    if base_phase == "P":
        if error_type == "syntax":
            return "Ps"
        if error_type == "import":
            return "Pi"
        if is_repatch:
            return "Pr"
        return "P"
    if base_phase == "V":
        if error_type == "test_failure":
            return "Vf"
        if error_type in {"syntax", "import", "runtime"}:
            return "Ve"
        return "Vp"
    if base_phase == "E":
        return "E"
    return "G"


def _extract_python_c_body(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    for index, part in enumerate(parts):
        if part == "-c" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _is_inline_reproduction(body: str) -> bool:
    body_lower = body.lower()
    if not re.search(r"\bassert\b|print\s*\(", body_lower):
        return False

    return bool(
        re.search(r"\b(repro(?:duce|duction)?|regression|minimal failing|minimal example)\b", body_lower)
        or re.search(r"expected.{0,120}(actual|got|instead)", body_lower, re.DOTALL)
        or re.search(
            r"should(?:\s+\w+){0,8}\s+be.{0,120}(but\s+is|got|instead)",
            body_lower,
            re.DOTALL,
        )
        or re.search(
            r"issue:.{0,160}(expected|actual|should|but\s+is|got|instead)",
            body_lower,
            re.DOTALL,
        )
    )

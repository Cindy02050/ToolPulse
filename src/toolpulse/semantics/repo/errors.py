"""Error classification for validation/patch actions (repo-language scope).

Port of legacy ``sweagent/agent/algorithm/utils/action_error.py``.

Adaptations vs legacy (behaviour-preserving):

- ``observation`` is an explicit parameter: legacy read it from the action
  dict (``action.get("observation")``); ``Action`` does not carry an
  observation.
- every other action-dict read became an attribute read
  (``action.get("args")`` → ``action.args``, ``action.get("raw_action")`` →
  ``action.raw_action``, ``action.get("tool")`` → ``action.tool``).

The python-default detection logic lives in this module. The cpp/java
branches delegate to the language packs, imported lazily inside the branch
bodies so that importing this module never loads a language pack — the
registry (``toolpulse.semantics.repo.languages``) stays the single eager
entry point.
"""

from __future__ import annotations

import re
import shlex

from toolpulse.core.types import Action

SYNTAX_ERRORS = {"SyntaxError", "IndentationError"}
IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError"}
RUNTIME_ERRORS = {
    "TypeError",
    "AttributeError",
    "RuntimeError",
    "ValueError",
    "KeyError",
    "IndexError",
    "NameError",
    "FileNotFoundError",
    "OSError",
    "PermissionError",
    "ZeroDivisionError",
    "NotImplementedError",
    "RecursionError",
    "StopIteration",
}
PYTHON_COMMANDS = {
    "python",
    "python2",
    "python3",
    "python3.6",
    "python3.7",
    "python3.8",
}
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TIMEOUT_PATTERN = re.compile(
    r"timed out|timeout|took more than \d+ seconds|was cancelled",
    re.IGNORECASE,
)
PYTHON_NO_MODULE_PATTERN = re.compile(
    r"^\s*\S*python(?:\d+(?:\.\d+)*)?:\s+No module named\s+\S+",
    re.IGNORECASE | re.MULTILINE,
)
TRACEBACK_MARKER = "Traceback (most recent call last):"
TRACEBACK_EXCEPTION_PATTERN = re.compile(r"^(?:[A-Za-z_]\w*\.)*[A-Z]\w*(?::.*)?$")


def action_error_type(action: Action, observation: str, language: str = "python") -> str:
    """Return the detected error type for a validation or patch action."""
    if not action or not _is_validation_or_patch_action(action, language):
        return "none"

    observation = str(observation or "")
    if language == "python":
        return _detect_observation_error_type(observation)
    return detect_observation_error_type_for_language(observation, language)


def detect_observation_error_type_for_language(observation: str, language: str) -> str:
    """Try the java/cpp adapter first, then fall back to the shared detector."""
    if language == "java":
        from toolpulse.semantics.repo.languages.java import (
            detect_observation_error_type as detect_observation_error_type_java,
        )

        result = detect_observation_error_type_java(observation)
        if result != "none":
            return result
    elif language == "cpp":
        from toolpulse.semantics.repo.languages.cpp import (
            detect_observation_error_type as detect_observation_error_type_cpp,
        )
        from toolpulse.semantics.repo.languages.cpp import (
            sanitize_non_compiler_error_tokens,
        )

        result = detect_observation_error_type_cpp(observation)
        if result == "pass":
            # Authoritative clean run: skip the shared detector so its generic
            # "FAILED"/"error:" rules cannot misfire on verbose success output.
            return "none"
        if result != "none":
            return result
        # The shared detector's bare-`error:` rule exists for python tracebacks;
        # neutralize the non-compiler occurrences before falling back.
        observation = sanitize_non_compiler_error_tokens(observation)
    return _detect_observation_error_type(observation)


def action_has_error(action: Action, observation: str) -> bool:
    """Return whether a validation or patch action produced an error."""
    # Legacy parity: this helper called ``action_error_type`` without the
    # language argument, so it always classifies with the python default.
    return action_error_type(action, observation) != "none"


def observation_error_fingerprint(observation: str, error_type: str) -> str | None:
    """Return a normalized triggering line for an already detected error type."""
    if error_type == "test_failure":
        return "test_failure"
    if error_type not in {"syntax", "import", "runtime"} or not observation:
        return None

    lines = observation.splitlines()
    if error_type == "syntax":
        return _last_normalized_line_containing(lines, SYNTAX_ERRORS) or _fallback_error_fingerprint(lines)
    if error_type == "import":
        fingerprint = _last_normalized_line_containing(lines, IMPORT_ERRORS)
        if fingerprint is not None:
            return fingerprint
        return next(
            (_normalize_error_line(line) for line in lines if PYTHON_NO_MODULE_PATTERN.search(line)),
            None,
        ) or _fallback_error_fingerprint(lines)

    timeout_line = next((line for line in lines if TIMEOUT_PATTERN.search(line)), None)
    if timeout_line is not None:
        return _normalize_error_line(timeout_line)

    traceback_start = max(
        (index for index, line in enumerate(lines) if TRACEBACK_MARKER in line),
        default=-1,
    )
    if traceback_start >= 0:
        for line in reversed(lines[traceback_start + 1 :]):
            normalized = _normalize_error_line(line)
            if TRACEBACK_EXCEPTION_PATTERN.fullmatch(normalized):
                return normalized
        return _fallback_error_fingerprint(lines)

    return _last_normalized_line_containing(lines, RUNTIME_ERRORS) or _fallback_error_fingerprint(lines)


def _fallback_error_fingerprint(lines: list[str]) -> str | None:
    """Keep recognized non-Python errors clusterable without a language pack.

    Prefer a diagnostic over a trailing summary/footer. This intentionally broad
    fallback only runs AFTER error classification; it never turns success into
    failure. Preserve specific Python fingerprints above for compatibility.
    """
    normalized = [_normalize_error_line(line) for line in lines]
    diagnostic = re.compile(
        r"error|exception|fatal|fail(?:ed|ure)?|segmentation|aborted|cannot"
        r"|not found|undefined reference", re.IGNORECASE,
    )
    summary = re.compile(
        r"^\d+\s+(?:errors?|warnings?|failures?|failed)\b"
        r"|\bld returned \d+ exit status\b|\blinker command failed with exit code \d+\b",
        re.IGNORECASE,
    )
    return next((line for line in reversed(normalized) if line and diagnostic.search(line) and not summary.search(line)),
                next((line for line in reversed(normalized) if line), None))


def _last_normalized_line_containing(lines: list[str], markers: set[str]) -> str | None:
    for line in reversed(lines):
        if any(marker in line for marker in markers):
            return _normalize_error_line(line)
    return None


def _normalize_error_line(line: str) -> str:
    without_ansi = ANSI_ESCAPE_PATTERN.sub("", line)
    return " ".join(without_ansi.split())


def _is_validation_or_patch_action(action: Action, language: str = "python") -> bool:
    tool = str(action.tool or "")
    args = action.args

    if tool == "str_replace_editor":
        command = str(args.get("command", "")) if isinstance(args, dict) else ""
        return command in {"create", "str_replace", "insert"}

    if tool in {"edit", "create"}:
        return True

    if not tool.startswith("bash-"):
        return False

    command = str(args or "").strip()
    command_name = tool.removeprefix("bash-")

    if language == "java":
        from toolpulse.semantics.repo.languages.java import (
            is_validation_command as is_validation_command_java,
        )

        if is_validation_command_java(command):
            return True
    if language == "cpp":
        from toolpulse.semantics.repo.languages.cpp import (
            is_validation_command as is_validation_command_cpp,
        )

        if is_validation_command_cpp(str(action.raw_action or command)):
            return True

    if command_name in PYTHON_COMMANDS:
        return _is_python_validation(command)

    if command_name == "pytest":
        return True

    if command_name in {"sed", "awk"}:
        if command_name == "sed" and re.search(r"-n\s+'?\d", command):
            return False
        return True

    command_lower = command.lower()
    if re.search(r"(>>|>\s)", command) and any(token in command_lower for token in ("cat ", "echo ", "printf ")):
        return True

    if command.startswith("./"):
        return True

    try:
        first_token = shlex.split(command)[0]
    except (ValueError, IndexError):
        first_token = command.split()[0] if command.split() else ""
    return first_token.startswith(("DJANGO_SETTINGS", "PYTHONPATH"))


def _is_python_validation(command: str) -> bool:
    if re.search(r"--help\b|-h\b", command) or "--version" in command:
        return False

    body = _extract_python_c_body(command)
    if body:
        lower = body.lower()
        if any(keyword in lower for keyword in ("version", "__version__", "sys.version")):
            return False

        has_code_definition = bool(re.search(r"^\s*(?:class|(?:async\s+)?def)\s+\w+", body, re.MULTILINE))
        if (
            re.match(r"^[\"']?\s*import\s+\w", body)
            and "assert" not in lower
            and "test" not in lower
            and not has_code_definition
        ):
            return False

    return True


def _extract_python_c_body(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    for index, part in enumerate(parts):
        if part == "-c" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _detect_observation_error_type(observation: str) -> str:
    if not observation:
        return "none"

    if TIMEOUT_PATTERN.search(observation):
        return "runtime"

    if any(error in observation for error in SYNTAX_ERRORS):
        return "syntax"

    if any(error in observation for error in IMPORT_ERRORS):
        return "import"

    if PYTHON_NO_MODULE_PATTERN.search(observation):
        return "import"

    if "FAILED" in observation or "AssertionError" in observation:
        return "test_failure"

    if re.search(r"[1-9]\d* failed", observation):
        return "test_failure"

    if TRACEBACK_MARKER in observation:
        return "runtime"

    for line in observation.splitlines():
        if re.search(r"\bexpected\b", line, re.IGNORECASE):
            continue
        if re.search(r"\berror:", line, re.IGNORECASE):
            return "runtime"

    if any(error in observation for error in RUNTIME_ERRORS):
        return "runtime"

    return "none"

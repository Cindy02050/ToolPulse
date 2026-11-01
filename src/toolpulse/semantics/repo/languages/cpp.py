"""C++-specific adapters for the semantic action labeler.

Only consulted when the task language is "cpp" (see action_semantic /
action_error routing). Every function falls back to the shared python-era
logic by returning ``None`` / ``"none"`` / ``False`` on anything it does not
recognize, so generic commands (grep, find, cat, edits, ...) keep using the
shared classifiers.
"""

from __future__ import annotations

import re
import shlex

CPP_COMPILER_PATTERN = re.compile(
    r"^(?:g\+\+|gcc|clang\+\+|clang|cc|c\+\+)(?:-\d+(?:\.\d+)*)?$"
)
CPP_VERSION_FLAG_PATTERN = re.compile(r"(?:^|\s)--version(?:\s|$)")
CPP_BUILD_TOOLS = {"cmake", "cmake3", "ninja", "meson", "make", "gmake", "configure", "autoreconf"}
CPP_TEST_RUNNERS = {"ctest"}
CPP_TEST_GOAL_PATTERN = re.compile(r"(?:^|\s)(?:test|check)s?(?:\s|$|-)", re.IGNORECASE)
CPP_REPRO_NAME_PATTERN = re.compile(r"repro(?:duce|duction)?s?(?:$|[_\d.])", re.IGNORECASE)

# Basenames that the shared classifier already handles (reads, searches,
# file management, python, ...). Absolute/relative-path tokens whose basename
# is in this set are left to the shared logic instead of being treated as
# compiled test binaries.
SHARED_UTILITY_BASENAMES = {
    "find", "grep", "rg", "ag", "cat", "head", "tail", "less", "more", "ls", "dir",
    "sed", "awk", "echo", "printf", "wc", "sort", "uniq", "diff", "cmp", "git",
    "rm", "mkdir", "mv", "cp", "touch", "chmod", "ln", "which", "whereis", "env",
    "bash", "sh", "zsh", "xargs", "tee", "true", "false", "pwd", "export", "source",
    "tar", "unzip", "gzip", "curl", "wget", "man", "col", "column", "tr", "cut",
    "patch", "apply_patch", "submit", "cd", "pip", "pip3", "pytest", "timeout",
    "file", "stat", "du", "df", "ps", "kill", "sleep", "date", "whoami",
}
SHARED_UTILITY_BASENAME_PATTERN = re.compile(r"^python\d*(?:\.\d+)?$")

CPP_TEST_FAILURE_PATTERN = re.compile(
    r"\[\s+FAILED\s+\]"
    r"|[1-9]\d* failed"
    r"|[1-9]\d* tests? failed"
    r"|test cases?:[^\n]*[1-9]\d* failed",
    re.IGNORECASE,
)
CPP_CRASH_PATTERN = re.compile(
    r"Segmentation fault"
    r"|core dumped"
    r"|\bAborted\b"
    r"|terminate called after throwing"
    r"|Assertion [^\n]{0,200} failed"
    r"|what\(\):"
    r"|command not found",
)
# Compiler diagnostics always carry a position prefix (file:line[:col]: error:)
# or an emitter prefix (fatal error:, collect2:, g++:). A bare `error:` token
# also appears in ordinary program output ("error: SUCCESS: No error",
# "type_error::create", "Error: Parameter conversion ...") and must not be
# treated as a compile error.
CPP_COMPILE_ERROR_PATTERN = re.compile(
    r":\d+(?::\d+)?: error:"
    r"|\bfatal error:"
    r"|collect2: error:"
    r"|(?:g\+\+|gcc|clang\+\+|clang|cc|c\+\+): error:"
    r"|undefined reference to"
    r"|ld returned \d+ exit status"
    r"|compilation terminated"
    r"|No such file or directory",
    re.IGNORECASE,
)
CPP_TIMEOUT_PATTERN = re.compile(
    r"timed out|timeout|took more than \d+ seconds|was cancelled",
    re.IGNORECASE,
)
CPP_PASS_BANNER_PATTERN = re.compile(
    r"All tests passed"
    r"|\[\s+PASSED\s+\]"
    r"|100% tests passed"
    r"|\b\d+/\d+ tests? passed",
    re.IGNORECASE,
)
_BARE_ERROR_TOKEN_PATTERN = re.compile(r"\berror:", re.IGNORECASE)
_HEREDOC_START_PATTERN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SHELL_SEPARATOR_PATTERN = re.compile(r"&&|\|\||;|\n")
_LEADING_CONTROL_PATTERN = re.compile(r"^(?:(?:do|then)\s+)+")
_LEADING_CD_PATTERN = re.compile(r"^\s*cd\s+([^\s;&]+)\s*&&")
_PYTHON_OPEN_WRITE_PATTERN = re.compile(
    r"\bopen\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"](?:w|a|x|r\+)[^'\"]*['\"]"
)
_PYTHON_PATH_WRITE_PATTERN = re.compile(
    r"\bPath\(\s*['\"]([^'\"]+)['\"]\s*\)\.(?:write_text|write_bytes)\s*\("
)
_CPP_PATCH_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp")


def _basename(first_word: str) -> str:
    return first_word.rsplit("/", 1)[-1]


def _is_shared_utility(basename: str) -> bool:
    return basename in SHARED_UTILITY_BASENAMES or bool(SHARED_UTILITY_BASENAME_PATTERN.match(basename))


def _classify_simple_command(command: str) -> tuple[str, str] | None:
    first_word = command.split()[0] if command.split() else ""
    if not first_word:
        return None
    basename = _basename(first_word)
    is_path_token = "/" in first_word

    if CPP_COMPILER_PATTERN.match(basename):
        if CPP_VERSION_FLAG_PATTERN.search(command):
            return ("E", "environment")
        if CPP_REPRO_NAME_PATTERN.search(command):
            return ("V", "reproduce")
        return ("V", "run_code")

    if basename in CPP_TEST_RUNNERS:
        return ("V", "run_tests")

    if basename in CPP_BUILD_TOOLS:
        if basename in {"make", "gmake", "ninja"} and CPP_TEST_GOAL_PATTERN.search(command):
            return ("V", "run_tests")
        return ("E", "environment")

    if basename in {"bash", "sh"}:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if len(parts) > 1:
            script_basename = _basename(parts[1])
            if CPP_REPRO_NAME_PATTERN.search(script_basename) or re.search(
                r"(?:^|[_-])(?:test|tests|run_tests)(?:$|[_\d.-])",
                script_basename,
                re.IGNORECASE,
            ):
                return ("V", "reproduce")

    # Compiled binaries: executed via an absolute/relative path (`/tmp/reproduce`,
    # `build/test_x`, `./reproduce2`) or as a bare reproduce-style name.
    looks_like_binary = (is_path_token or CPP_REPRO_NAME_PATTERN.search(basename)) and not _is_shared_utility(basename)
    if looks_like_binary:
        if CPP_REPRO_NAME_PATTERN.search(basename):
            return ("V", "reproduce")
        return ("V", "run_code")

    return None


def _without_heredoc_bodies(command: str) -> str:
    """Return shell control lines while omitting heredoc payloads."""
    result: list[str] = []
    delimiter: str | None = None
    for line in command.splitlines():
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        result.append(line)
        match = _HEREDOC_START_PATTERN.search(line)
        if match:
            delimiter = match.group(2)
    return "\n".join(result)


def _command_segments(command: str) -> list[str]:
    control_text = _without_heredoc_bodies(command)
    segments: list[str] = []
    for piece in _SHELL_SEPARATOR_PATTERN.split(control_text):
        segment = _LEADING_CONTROL_PATTERN.sub("", piece.strip())
        if segment:
            segments.append(segment)
    return segments


def _aggregate_classifications(classifications: list[tuple[str, str]]) -> tuple[str, str] | None:
    for phase in ("V", "P", "L", "E"):
        matching = [classification for classification in classifications if classification[0] == phase]
        if not matching:
            continue
        if phase == "V":
            if any(action_type == "run_tests" for _, action_type in matching):
                return ("V", "run_tests")
            if any(action_type == "reproduce" for _, action_type in matching):
                return ("V", "reproduce")
        if phase == "L":
            if any(action_type in {"search_precise", "search_broad"} for _, action_type in matching):
                return ("L", "search_precise")
            if any(action_type == "read_targeted" for _, action_type in matching):
                return ("L", "read_targeted")
        return matching[0]
    return None


def _cpp_control_classification(command: str) -> tuple[str, str] | None:
    classifications: list[tuple[str, str]] = []
    for segment in _command_segments(command):
        classification = _classify_simple_command(segment)
        if classification is not None:
            classifications.append(classification)
            continue
        first_word = segment.split()[0] if segment.split() else ""
        if first_word == "sed" and re.search(r"(?:^|\s)-n(?:\s|$)", segment):
            classifications.append(("L", "read_targeted"))
    return _aggregate_classifications(classifications)


def _working_directory(command: str) -> str | None:
    match = _LEADING_CD_PATTERN.search(command)
    if not match:
        return None
    return match.group(1).strip("'\"")


def _normalize_patch_target(path: str, working_directory: str | None) -> str | None:
    path = path.strip("'\"")
    if path.startswith("/tmp/") or not path.endswith(_CPP_PATCH_SUFFIXES):
        return None
    if path.startswith("/") or not working_directory:
        return path
    return working_directory.rstrip("/") + "/" + path.lstrip("/")


def extract_patch_target(command: str) -> str | None:
    """Extract a C++ source target from shell/Python edits in a raw action."""
    working_directory = _working_directory(command)
    for pattern in (_PYTHON_OPEN_WRITE_PATTERN, _PYTHON_PATH_WRITE_PATTERN):
        for match in pattern.finditer(command):
            target = _normalize_patch_target(match.group(1), working_directory)
            if target:
                return target

    for segment in _command_segments(command):
        if not re.match(r"^sed\s+", segment) or not re.search(r"(?:^|\s)-i(?:\s|$)", segment):
            continue
        try:
            parts = shlex.split(segment)
        except ValueError:
            parts = segment.split()
        if len(parts) < 3:
            continue
        target = _normalize_patch_target(parts[-1], working_directory)
        if target:
            return target
    return None


def classify_bash_command(command: str) -> tuple[str, str] | None:
    """Classify a C++ shell action, including compound raw actions."""
    command = command.strip()
    if not command:
        return None

    if extract_patch_target(command) is not None and re.search(r"\bpython\d*(?:\.\d+)?\b", command):
        return ("P", "edit")

    return _cpp_control_classification(command)


def detect_observation_error_type(observation: str) -> str:
    """Detect cpp-specific error markers; ``"none"`` falls back to shared logic.

    ``"pass"`` is an authoritative clean result (test-framework success
    banner): the caller must return "none" without consulting the shared
    detector, whose generic ``FAILED``/``error:`` rules misfire on verbose
    success output such as Catch2's ``FAILED - but was ok`` lines.
    """
    if not observation:
        return "none"

    if CPP_TEST_FAILURE_PATTERN.search(observation):
        return "test_failure"
    if CPP_CRASH_PATTERN.search(observation):
        return "runtime"
    if CPP_COMPILE_ERROR_PATTERN.search(observation):
        return "syntax"
    if CPP_TIMEOUT_PATTERN.search(observation):
        return "runtime"
    if CPP_PASS_BANNER_PATTERN.search(observation):
        return "pass"
    return "none"


def sanitize_non_compiler_error_tokens(observation: str) -> str:
    """Rewrite ``error:`` tokens that are not part of compiler diagnostics.

    The shared detector treats any ``error:`` line as a runtime error (a
    python-era rule). In cpp trajectories that rule misfires on ordinary
    program prints such as ``error: SUCCESS: No error`` or ``Error: Parameter
    conversion ...``; real compiler diagnostics keep their ``error:`` token
    because they match :data:`CPP_COMPILE_ERROR_PATTERN` and are protected.
    """
    protected = [m.span() for m in CPP_COMPILE_ERROR_PATTERN.finditer(observation)]
    pieces: list[str] = []
    prev = 0
    for match in _BARE_ERROR_TOKEN_PATTERN.finditer(observation):
        start, end = match.span()
        if any(p_start <= start and end <= p_end for p_start, p_end in protected):
            continue
        pieces.append(observation[prev:start])
        pieces.append("error ·")
        prev = end
    pieces.append(observation[prev:])
    return "".join(pieces)


def is_validation_command(command: str) -> bool:
    """Return whether a bash command is a cpp build/test/run worth error-checking."""
    command = command.strip()
    if not command:
        return False
    return any(
        classification is not None and classification[0] in {"V", "E"}
        for classification in (_classify_simple_command(segment) for segment in _command_segments(command))
    )

"""Java-specific adapters for the semantic action labeler.

Only consulted when the task language is "java" (see action_semantic /
action_error routing). Every function falls back to the shared python-era
logic by returning ``None`` / ``"none"`` / ``False`` on anything it does not
recognize, so generic commands (grep, find, cat, edits, ...) keep using the
shared classifiers.
"""

from __future__ import annotations

import re

JAVA_BUILD_TOOLS = {"mvn", "mvnd", "mvnw", "gradle", "gradlew"}
JAVA_RUN_COMMANDS = {"java", "javac", "javap", "jshell", "jdb"}
JAVA_PACK_COMMANDS = {"jar"}

MAVEN_TEST_GOAL_PATTERN = re.compile(r"(?:^|\s)(?:test|verify|check)(?:\s|$)|-Dtest=", re.IGNORECASE)
GRADLE_TEST_TASK_PATTERN = re.compile(r"(?:^|\s)(?:\S*:)?(?:test|check)(?:\s|$)|(?:^|\s)check\s", re.IGNORECASE)
VERSION_FLAG_PATTERN = re.compile(r"(?:^|\s)-(?:-)?version(?:\s|$)")

JAVA_COMPILE_ERROR_PATTERN = re.compile(
    r"COMPILATION ERROR|Compilation failure|cannot find symbol"
    r"|package [\w.]+ does not exist"
    r"|\.java:\[\d+,\d+\] error"
    r"|\.java:\d+: error",
    re.IGNORECASE,
)
JAVA_TEST_FAILURE_PATTERN = re.compile(
    r"Tests run:.*Failures:\s*[1-9]"
    r"|Tests run:.*Errors:\s*[1-9]"
    r"|Tests in error"
    r"|There are test failures"
    r"|> Task :[^ ]* FAILED"
    r"|[1-9]\d* tests? (?:completed|failed)",
    re.IGNORECASE,
)
JAVA_RUNTIME_ERROR_PATTERN = re.compile(
    r"BUILD FAILURE|BUILD FAILED|Exception in thread|Caused by:"
    r"|command not found"
    r"|javac: invalid flag"
    r"|javac: directory not found"
    r"|error: no source files"
    r"|\[FATAL\]"
    r"|Some problems were encountered while processing the POMs"
    r"|Non-resolvable"
    r"|Unresolveable build extension"
    r"|Could not find artifact",
)


def _basename(first_word: str) -> str:
    return first_word.rsplit("/", 1)[-1]


def classify_bash_command(command: str) -> tuple[str, str] | None:
    """Classify a java-specific bash command; ``None`` if not java-specific."""
    command = command.strip()
    if not command:
        return None

    first_word = command.split()[0]
    basename = _basename(first_word)

    if basename in JAVA_BUILD_TOOLS:
        if VERSION_FLAG_PATTERN.search(command):
            return ("E", "environment")
        if basename == "gradle" or basename == "gradlew":
            if GRADLE_TEST_TASK_PATTERN.search(command):
                return ("V", "run_tests")
        elif MAVEN_TEST_GOAL_PATTERN.search(command):
            return ("V", "run_tests")
        return ("E", "environment")

    if basename in JAVA_RUN_COMMANDS:
        if VERSION_FLAG_PATTERN.search(command):
            return ("E", "environment")
        return ("V", "run_code")

    if basename in JAVA_PACK_COMMANDS:
        return ("E", "environment")

    return None


def detect_observation_error_type(observation: str) -> str:
    """Detect java-specific error markers; ``"none"`` falls back to shared logic."""
    if not observation:
        return "none"

    if JAVA_COMPILE_ERROR_PATTERN.search(observation):
        return "syntax"
    if JAVA_TEST_FAILURE_PATTERN.search(observation):
        return "test_failure"
    if JAVA_RUNTIME_ERROR_PATTERN.search(observation):
        return "runtime"
    return "none"


def is_validation_command(command: str) -> bool:
    """Return whether a bash command is a java build/test/run worth error-checking."""
    command = command.strip()
    if not command:
        return False

    basename = _basename(command.split()[0])
    return basename in JAVA_BUILD_TOOLS | JAVA_RUN_COMMANDS | JAVA_PACK_COMMANDS

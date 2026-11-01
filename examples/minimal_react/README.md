# ToolPulse + minimal ReAct

[English](README.md) | [简体中文](README.zh-CN.md)

This is a second framework integration alongside SWE-agent. The framework consists of a directly editable ReAct loop, two actions, and a scripted decision function. It needs no model, network, Docker, or SWE-agent.

The action parser and semantic definitions belong to ToolPulse's `src`; this directory provides the framework's tools, loop, and demo task. Scripted decisions make the demo reproducible, while tool results come from actual in-memory operations.

## Run

From the ToolPulse repository root:

```bash
python -m pip install -e .
python examples/minimal_react/run.py
python examples/minimal_react/run.py --hint-set different_message_type
```

The task is to change the in-memory file `note.txt` to `ready`, then check it. The default sequence contains seven tool calls:

| Step | Action | Result and feedback |
|---|---|---|
| 1 | Write `broken` | Pre-check flags Blind Command; this example still executes the call |
| 2 | Read the file | Returns `broken` and establishes a read record |
| 3 | Check for `ready` | Fails |
| 4 | Check again | Fails; post-analysis warns about Failure Inertia |
| 5 | Check a third time | Fails; post-analysis flags Calling Repetition |
| 6 | Write `ready` | Succeeds; OPERATE clears failure clusters under the existing heuristic |
| 7 | Check for `ready` | Succeeds; the step is recorded before the loop finishes |

Each turn prints Thought, Action, and Observation with any hints, followed by `Finished` at the end. All file operations use a dictionary and leave disk files untouched.

## Framework components in src

| File | Responsibility |
|---|---|
| [`parsing/minimal_react.py`](../../src/toolpulse/parsing/minimal_react.py) | `MinimalReactParser`: converts framework JSON actions to `Action`, validating tool names and required arguments |
| [`semantics/minimal_react/labeler.py`](../../src/toolpulse/semantics/minimal_react/labeler.py) | `KIND_OF_LABEL` and `MinimalReactLabeler`: semantic labels, file attributes, error types and fingerprints, and post-execution edit records |
| [`middleware.py`](../../src/toolpulse/middleware.py) | `ToolPulse.for_minimal_react()`: assembles this framework's parser and labeler, reusing other components |

Public imports also support explicit assembly:

```python
from toolpulse import MinimalReactLabeler, MinimalReactParser, ToolPulse

pulse = ToolPulse(
    parser=MinimalReactParser(),
    labeler=MinimalReactLabeler(),
)
# Equivalent framework preset: pulse = ToolPulse.for_minimal_react()
```

An action is a JSON string containing `tool` and `args`. The two tools accept these arguments:

```json
{"tool": "file", "args": {"mode": "read", "path": "note.txt"}}
{"tool": "file", "args": {"mode": "write", "path": "note.txt", "content": "ready"}}
{"tool": "check", "args": {"path": "note.txt", "expected": "ready"}}
```

`file/write` only edits existing files; this example has no file-creation action. Blank input parses as an empty action. Other invalid JSON, tools, or arguments raise `ValueError` during pre-check, before execution or recording.

An observation is also a JSON string: either `{"ok": true, ...}` or `{"ok": false, "error": "nonempty error description"}`. Successful reads include `content`. During post-analysis, the labeler maps failed `check` calls to `test_failure` and failed file operations to `runtime`; the complete error description is the stable fingerprint. This suits the demo's fixed error format. A real framework should normalize fingerprints according to its own error protocol.

| Semantic label | Kind | Condition |
|---|---|---|
| `read` | RETRIEVE | `file/read` |
| `write` | OPERATE | `file/write` |
| `check_ok` | COMPUTE | Check reports no error |
| `check_failed` | COMPUTE | Check fails |
| `empty` | OTHER | Fallback for blank actions |

The three main kinds have only 1, 1, and 2 labels respectively. Custom labels feed directly into the grammar; the core display function passes unknown labels through, so the global label table needs no changes. Before execution, a check temporarily receives `check_ok` because no result exists yet; pre-check does not commit it to the trajectory.

`LabelInfo` attributes enable the shared detector: `target_file` identifies the path, `is_patch` marks writes, and `is_create=False` reflects the absence of file creation. Only successful reads set `is_read` during post-analysis, allowing the detector to record file knowledge. The labeler calls `record_edit()` only after a successful write; pre-check with `record=False` stays read-only. Error types and fingerprints reach failure detection through `LabelInfo.error`.

## Integration points in the loop

The `run()` function in [`run.py`](run.py) exposes the full sequence:

1. Call `reset()`, set the task description, and initialize task files and message history.
2. Let the decision function read history and return Thought and Action.
3. Construct `StepObservation` and call `inspect_action()`; this example warns and continues execution.
4. Execute the tool, attach its raw JSON result and elapsed time, then call `observe_step()` once.
5. Call `assemble_observation(raw_result, pre_hints + post_hints)`, append the result to history, and continue.
6. Finish when the decision function returns `None`, with a separate 20-step limit. Executed steps do not set `done=True`, so the final check also receives post-analysis.

Default hints use `<tool_pulse>...</tool_pulse>` tags. `different_message_type` produces a JSON string with `observation` and `hint` fields, still within the same message content. The default sink already collects hints; no extra delivery layer is needed.

`scripted_model(history)` counts past actions to select the next scripted step. Hints do not change its decisions. To build a real agent, replace this function with a model call that reads the same history and emits protocol-compliant actions. This example uses plain assistant/user text messages, so it needs no provider tool-call ID pairing.

## What to replace for another framework

| Integration responsibility | minimal ReAct | SWE-agent |
|---|---|---|
| Parse actions | `MinimalReactParser`, simple JSON | `SweAgentParser` plus a native tool-call parser |
| Define semantics | Its own label table and `MinimalReactLabeler` | Repo label table and `RepoLabeler` |
| Identify errors and file semantics | Explicit JSON results, paths, and read/write flags | Repo error parsing, tool arguments, and host context |
| Assemble components | `for_minimal_react()` | `for_swe_repo()`; the adapter installs a native tool-call parser |
| Pre / execution / post | Direct calls in this loop | Method overrides and an execution hook in `ToolPulseSWEAgent` |
| Feed hints into the next turn | Assemble observations and append to history | Adapt tool responses, host templates, clipping, and retry messages |
| New tasks and termination | Reset in `run()`; script exhaustion or step limit | Adapter setup, host termination, and refusal budget |

Detectors, session state, hint providers/sinks, and observation assembly are reusable. Extend them only when new detection rules or hint content are needed. SWE-agent requires an adapter to enter its existing lifecycle; this example's loop is directly editable, so it needs no additional agent class.

## Verification

```bash
python -m pytest -q tests/parsing/test_minimal_react.py \
  tests/semantics/test_minimal_react_labeler.py tests/test_minimal_react_example.py
```

Tests cover argument validation, read-only pre-checks, file read/write semantics, failure clustering, and the complete demo with both plain and JSON feedback.

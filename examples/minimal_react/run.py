"""A complete, scripted ReAct loop with ToolPulse. No model or network needed."""
from __future__ import annotations

import argparse
import json
from time import perf_counter

from toolpulse import StepObservation, TemplateHintRenderer, ToolPulse


TASK = "Change note.txt to ready, then check that its content is ready."

# A deterministic stand-in for model reasoning. Deliberate mistakes show hints.
SCRIPT = [
    ("Try writing before reading.", {"tool": "file", "args": {"mode": "write", "path": "note.txt", "content": "broken"}}),
    ("Inspect the file.", {"tool": "file", "args": {"mode": "read", "path": "note.txt"}}),
    ("Check the result.", {"tool": "check", "args": {"path": "note.txt", "expected": "ready"}}),
    ("Repeat without fixing it.", {"tool": "check", "args": {"path": "note.txt", "expected": "ready"}}),
    ("Repeat once more.", {"tool": "check", "args": {"path": "note.txt", "expected": "ready"}}),
    ("Write the required content.", {"tool": "file", "args": {"mode": "write", "path": "note.txt", "content": "ready"}}),
    ("Verify the fix.", {"tool": "check", "args": {"path": "note.txt", "expected": "ready"}}),
]


def scripted_model(history):
    """Replace this function with a model reading history to make it adaptive.

    Here history only selects the next scripted turn; hints do not change it.
    Returning None finishes the task without generating another tool action.
    """
    turn = sum(message["role"] == "assistant" for message in history)
    return SCRIPT[turn] if turn < len(SCRIPT) else None


def execute(action, files):
    """The framework's two tools. Files live in memory; write edits existing files."""
    tool, args = action["tool"], action["args"]
    path = args["path"]
    if path not in files:
        return {"ok": False, "error": f"File does not exist: {path}"}
    if tool == "file":
        if args["mode"] == "read":
            return {"ok": True, "content": files[path]}
        files[path] = args["content"]
        return {"ok": True}
    if files[path] == args["expected"]:
        return {"ok": True}
    return {"ok": False, "error": f"Expected {args['expected']!r}, got {files[path]!r}"}


def run(pulse: ToolPulse, max_steps: int = 20):
    # One pulse per agent. Reset it when starting a new task.
    pulse.reset()
    pulse.set_task_description(TASK)
    files = {"note.txt": "old"}
    history = [{"role": "user", "content": TASK}]

    for _ in range(max_steps):
        decision = scripted_model(history)                       # Thought + Action
        if decision is None:
            print("Finished")
            break
        thought, action = decision
        raw_action = json.dumps(action, ensure_ascii=False)
        step = StepObservation(raw_action=raw_action, thought=thought)
        pre = pulse.inspect_action(step)                         # 1. pre: no recording
        # Warn-only policy: even a blind edit executes in this small example.
        started = perf_counter()
        result = execute(action, files)                          # 2. actual execution
        step.execution_time = perf_counter() - started
        step.observation = json.dumps(result, ensure_ascii=False)
        post = pulse.observe_step(step)                          # 3. post: record once
        observation = pulse.assemble_observation(                # 4. feed back hints
            step.observation, [*pre.hints, *post],
        )
        history.append({"role": "assistant", "content": f"Thought: {thought}\nAction: {raw_action}"})
        history.append({"role": "user", "content": observation})
        print(f"Thought: {thought}\nAction: {raw_action}\nObservation: {observation}\n")
    else:
        print("Step limit reached")
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hint-set", default="remind_only", choices=[
        "remind_only", "remind_and_guide", "different_message_type",
    ])
    args = parser.parse_args()
    pulse = ToolPulse.for_minimal_react(
        hint_renderer=TemplateHintRenderer(hint_set_name=args.hint_set),
    )
    run(pulse)


if __name__ == "__main__":
    main()

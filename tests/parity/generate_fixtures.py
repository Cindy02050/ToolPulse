# tests/parity/generate_fixtures.py
"""Replay legacy .traj files through BOTH implementations and freeze golden fixtures.

Run from /root/OmniCode/ToolPulse:
    python tests/parity/generate_fixtures.py
Manual review of divergence flags is required before freezing (design §9.2, D12/D13/D14).

One fixture per named trajectory in ``TRAJS``: ``fixtures/<name>.json``.  The
``sweagenttestrepo`` fixture is the original 5-step happy path; the ``pydicom``
fixture comes from a richer real SWE-bench trajectory (failed edits with syntax
errors, a traceback run, a SKIP-classed ``rm``, ``submit``) so the parity tests
exercise the labeler, failure clusters, read recording and grammar feeding on
real data, not just the happy path.

Observed .traj shape (inspected before writing this loader): top level is
``{environment, trajectory, history, info, replay_config}``; ``trajectory`` is a
list of step dicts ``{action: str, observation: str, response, thought: str,
execution_time: float, state: {open_file, working_dir}}``.  Actions in these
files are plain strings; the loader still normalizes the newer dict form
``{"action": ..., "thought": ...}`` defensively if a future .traj uses it.
``state`` is a mapping in the older .traj and a JSON *string* in the pydicom
one; the loader normalizes both to a mapping.

Legacy hint capture is intentionally skipped: legacy hints are produced by
``ToolFamiliar`` into ``extra_info`` and hint parity is template-level (already
covered by tests/hints/test_template.py).  Events are the contract here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TRAJS: list[tuple[str, Path]] = [
    ("sweagenttestrepo", Path(
        "/root/OmniCode/SWE-agent/tests/test_data/trajectories/"
        "gpt4__swe-agent-test-repo__default_from_url__t-0.00__p-0.95__c-3.00__install-1/"
        "6e44b9__sweagenttestrepo-1c2844.traj")),
    ("pydicom", Path(
        "/root/OmniCode/SWE-agent/tests/test_data/trajectories/"
        "gpt4__swe-bench-dev-easy_first_only__default__t-0.00__p-0.95__c-3.00__install-1/"
        "pydicom__pydicom-1458.traj")),
]
SWE = "/root/OmniCode/SWE-agent"
OUT_DIR = Path(__file__).parent / "fixtures"


def load_steps(data: dict) -> list[dict]:
    """Normalize raw trajectory entries to a uniform step dict."""
    steps = []
    for entry in data.get("trajectory", []):
        if not isinstance(entry, dict) or "action" not in entry:
            continue
        action = entry["action"]
        if isinstance(action, dict):   # newer shape: {"action": ..., "thought": ...}
            raw_action = str(action.get("action", ""))
            thought = str(action.get("thought") or entry.get("thought", ""))
        else:
            raw_action = str(action)
            thought = entry.get("thought", "")
        steps.append({
            "action": raw_action,
            "thought": thought,
            "observation": entry.get("observation", ""),
            "execution_time": entry.get("execution_time", 0.0),
            "state": _load_state(entry),
        })
    return steps


def _load_state(entry: dict) -> dict:
    """Return the step state as a mapping (older .traj: dict; pydicom: JSON string)."""
    state = entry.get("state") or {}
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except json.JSONDecodeError:
            state = {}
    return state if isinstance(state, dict) else {}


def legacy_events_for(steps):
    """Drive the legacy brain exactly as ToolFamiliar.observe_step would.

    Mirrors ``ToolFamiliar._action_from_step`` + ``brain.analyze``:
    ``parse_action(raw, json.dumps(state))`` -> action dict -> ``analyze``.
    The brain is built offline=True so repeated regeneration cannot pollute
    suppression state (loop-report / stalled-cooldown bookkeeping); its
    ``reset()`` also clears the module-global edited/read-file sets, so each
    fixture generates independently of the others.
    """
    sys.path.insert(0, SWE)
    from sweagent.agent.algorithm.utils.action_semantic import action_semantic_label
    from sweagent.agent.tool_familiar import parse_action
    from sweagent.agent.algorithm.multi_granularity import MultiGranularityBrain
    brain = MultiGranularityBrain(offline=True)
    out = []
    for step in steps:
        action = {"tool": None, "args": {}, "raw_action": step["action"].strip(),
                  "observation": step["observation"], "thought": step["thought"],
                  "execution_time": step["execution_time"]}
        tool, args = parse_action(action["raw_action"], json.dumps(step.get("state") or {}))
        action.update(tool=tool, args=args)
        # True per-step label, read BEFORE analyze: brain.semantic_labels[-1]
        # goes stale on SKIP steps (legacy excludes them from its history), and
        # SKIP is exactly the former-skip class the divergence classifier must
        # recognize.  record_edit=False recomputes analyze's own label without
        # re-applying its edited-file side effect (a second record_edit=True
        # call would see its own mutation and mislabel first edits as Pr).
        label = action_semantic_label(action, record_edit=False, language=brain.language)
        events = brain.analyze(action)
        out.append({"events": events, "label": label})
    return out


def toolpulse_run(steps):
    """Replay the same step stream through ToolPulse with an offline detector.

    test_parity.py constructs its replay ToolPulse with exactly this
    configuration — keep them in sync (no ``for_swe_repo()`` shortcut).
    """
    from toolpulse.core.types import StepObservation
    from toolpulse.detectors.multi_granularity import MultiGranularityDetector
    from toolpulse.hints.sinks import ListSink
    from toolpulse.middleware import ToolPulse
    from toolpulse.parsing.sweagent import SweAgentParser
    from toolpulse.semantics.repo.labeler import RepoLabeler
    pulse = ToolPulse(parser=SweAgentParser(), labeler=RepoLabeler("python"),
                      detector=MultiGranularityDetector(offline=True), hint_sink=ListSink())
    sink = pulse.hint_sink
    out = []
    for step in steps:
        n_before = len(sink.hints)
        pulse.observe_step(StepObservation(
            raw_action=step["action"], observation=step["observation"],
            thought=step["thought"], execution_time=step["execution_time"],
            host_context=step.get("state")))
        fired = sink.hints[n_before:]
        out.append({"events": [h.event.to_dict() for h in fired]})
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, traj in TRAJS:
        data = json.loads(traj.read_text(encoding="utf-8"))
        steps = load_steps(data)
        legacy = legacy_events_for(steps)
        ours = toolpulse_run(steps)
        rows = []
        for step, leg, our in zip(steps, legacy, ours):
            same = leg["events"] == our["events"]
            rows.append({
                "action": step["action"], "thought": step["thought"],
                "observation": step["observation"],
                "execution_time": step["execution_time"],
                "host_context": step.get("state"),
                "legacy_label": leg["label"], "legacy_events": leg["events"],
                "toolpulse_events": our["events"],
                # Reviewer Minor 3: this events-only ternary cannot surface the
                # canonical D13 case (legacy excludes the action entirely while
                # ToolPulse records it as G with no event) — that divergence
                # class is pinned synthetically in test_new_goldens.py.
                "divergence": None if same else (
                    "D13-former-skip" if leg["label"] == "SKIP" else "review"),
            })
        out = OUT_DIR / f"{name}.json"
        out.write_text(json.dumps({"steps": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        flagged = [r for r in rows if r["divergence"]]
        print(f"{name}: {len(rows)} steps, {len(flagged)} divergent -> {out}")
        for i, row in enumerate(rows):
            if row["divergence"]:
                print(f"  step {i} [{row['divergence']}] label={row['legacy_label']!r}")
                print(f"    legacy:    {row['legacy_events']}")
                print(f"    toolpulse: {row['toolpulse_events']}")
                print(f"    observation: {row['observation'][:200]!r}")


if __name__ == "__main__":
    main()

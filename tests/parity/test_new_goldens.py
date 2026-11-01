# tests/parity/test_new_goldens.py
"""Deterministic new-behavior goldens for intentional divergences (D12/D13/D14).

Two deviations from the task brief's draft, both verified against the legacy
brain before freezing:

- ``test_d14_no_module_named_edge_uses_adjusted_channel``: the draft's input
  ``python -c 'import requests'`` classifies as E/environment in BOTH
  implementations (import-only ``-c`` body), so its ``kind == "compute"`` /
  ``label == "Ve"`` assertions could never hold.  The input is changed to a
  run_code action (``python /repo/run.py`` — legacy label Ve); all three
  assertions are the draft's verbatim.
- ``test_d14_vf_with_error_never_prunes_failure_clusters``: the draft asserted
  non-empty clusters after two IDENTICAL failures, but both implementations
  pop the cluster when the failed_action event fires at the repeat threshold
  (verified on the legacy brain).  The test now pins the actual invariant:
  a Vf step never prunes failure clusters (a second, different Vf leaves the
  registered cluster intact), with a Vp contrast showing the pass-prune still
  fires — strictly stronger than the draft.
"""
from toolpulse.core.types import StepObservation
from toolpulse.hints.sinks import ListSink
from toolpulse.middleware import ToolPulse
from toolpulse.semantics.repo.labeler import RepoLabeler


def _pulse():
    p = ToolPulse.for_swe_repo()
    sink = ListSink(); p.hint_sink = sink
    return p, sink


def test_former_skip_action_enters_sequence_as_other():
    pulse, _ = _pulse()
    pulse.observe_step(StepObservation(raw_action="cd /repo", observation=""))
    rec = pulse.state.actions[-1]
    assert rec.label.label == "G" and rec.label.kind.value == "other"
    assert pulse.state.grammar.symbols[-1] == "G"          # in grammar sequence (D13)
    assert pulse.state.total_actions_seen == 1


def test_d14_no_module_named_edge_uses_adjusted_channel():
    pulse, _ = _pulse()
    obs = "python3: No module named requests"
    pulse.observe_step(StepObservation(raw_action="python /repo/run.py", observation=obs))
    info = pulse.state.actions[-1].label
    assert info.error.kind == "import"                      # adjusted channel wins (D14)
    assert info.kind.value == "compute" and info.label == "Ve"


def test_d14_vf_with_error_never_prunes_failure_clusters():
    pulse, _ = _pulse()
    obs = "E   AssertionError: assert 1 == 2"
    pulse.observe_step(StepObservation(raw_action="pytest -q", observation=obs))
    assert pulse.state.failures.clusters                  # Vf does NOT act as pass-prune (invariant)
    # a second, different Vf on the same tool must leave the registered cluster intact
    pulse.observe_step(StepObservation(
        raw_action="pytest -q", observation="E   NameError: name 'x' is not defined"))
    assert ("bash-pytest", "test_failure", "test_failure") in pulse.state.failures.clusters
    # contrast: a passing run (Vp) still per-tool prunes failure clusters
    pulse.observe_step(StepObservation(raw_action="pytest -q", observation="2 passed"))
    assert not pulse.state.failures.clusters

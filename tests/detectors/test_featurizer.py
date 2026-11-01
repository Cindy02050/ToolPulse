import numpy as np
from toolpulse.detectors.featurizer import StepFeaturizer

F = StepFeaturizer()

def test_extract_returns_36d_compatible_row():
    row = F.extract(thought="hmm", tool="bash-python", args="python x.py",
                    observation="err", execution_time=1.5, has_error=True)
    assert len(row.tool_hash) == 16 and row.has_error is True and row.execution_time == 1.5

def test_transform_history_shape_and_warmup_zero():
    rows = [F.extract("t", "open", {}, "o", 0.1, has_error=False) for _ in range(4)]
    matrix = F.transform_history(rows)
    assert len(matrix) == 4 and all(v.shape == (36,) for v in matrix)

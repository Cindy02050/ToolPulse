# tests/state/test_features.py
import numpy as np
from toolpulse.core.types import RawFeaturesRow
from toolpulse.state.features import FeatureStore

def _row(i: float) -> RawFeaturesRow:
    return RawFeaturesRow(i, (i,) * 16, (i,) * 16, i, i, False)

def test_window_returns_vstacked_matrix():
    store = FeatureStore()
    store.append_row(_row(1.0)); store.append_row(_row(2.0))
    store.set_matrix([np.zeros(36), np.ones(36)])
    assert store.window(0, 2).shape == (2, 36)

def test_trim_removes_oldest_rows_in_lockstep():
    store = FeatureStore()
    for i in range(5):
        store.append_row(_row(float(i)))
    store.trim(2)   # keep last 3
    assert len(store) == 3 and store.rows[0].thought_length == 2.0

# tests/state/test_failures.py
from toolpulse.state.failures import FailureCluster, FailureTable

def test_expire_drops_old_clusters_only():
    table = FailureTable()
    table.clusters[("bash-python", "import", "f1")] = FailureCluster(count=1, last_seen_step=3)
    table.clusters[("bash-python", "runtime", "f2")] = FailureCluster(count=1, last_seen_step=10)
    table.expire(current_step=11, window=7)   # Legacy: retain entries when current - last_seen <= window
    assert ("bash-python", "import", "f1") not in table.clusters
    assert ("bash-python", "runtime", "f2") in table.clusters

def test_prune_by_tool_removes_only_that_tool():
    table = FailureTable()
    table.clusters[("bash-python", "import", "f1")] = FailureCluster(1, 1)
    table.clusters[("bash-pip", "runtime", "f2")] = FailureCluster(1, 1)
    table.prune_by_tool("bash-python")
    assert set(table.clusters) == {("bash-pip", "runtime", "f2")}

def test_snapshot_restore_roundtrips_pipe_containing_signature():
    # Regression (2026-10-31 final review): the old "|".join/split encoding corrupted
    # any signature whose tool/type/fingerprint itself contains "|".
    table = FailureTable()
    sig = ("bash-awk", "runtime", "syntax error near unexpected token `|'")
    table.clusters[sig] = FailureCluster(count=2, last_seen_step=5)
    table.clusters[("bash-python", "import|x", "fp")] = FailureCluster(1, 4)
    snap = table.snapshot()
    assert isinstance(snap, list)   # JSON-safe shape: [[list(sig), cluster-dict], ...]
    table2 = FailureTable()
    table2.restore(snap)
    assert set(table2.clusters) == {sig, ("bash-python", "import|x", "fp")}
    assert table2.clusters[sig] == FailureCluster(count=2, last_seen_step=5)

def test_snapshot_holds_no_live_cluster_references():
    table = FailureTable()
    table.clusters[("t", "runtime", "f")] = FailureCluster(1, 1)
    snap = table.snapshot()
    table.clusters[("t", "runtime", "f")].count = 99
    table2 = FailureTable()
    table2.restore(snap)
    assert table2.clusters[("t", "runtime", "f")].count == 1

def test_expire_boundary_age_equal_to_window_survives():
    # Legacy uses `<=`: age == window keeps the cluster; age == window+1 drops.
    table = FailureTable()
    table.clusters[("t", "runtime", "f")] = FailureCluster(count=1, last_seen_step=3)
    table.expire(current_step=11, window=8)   # age 11-3 == 8 → survives
    assert ("t", "runtime", "f") in table.clusters
    table.expire(current_step=12, window=8)   # age 12-3 == 9 → dropped
    assert ("t", "runtime", "f") not in table.clusters

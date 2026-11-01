# tests/state/test_files.py
from toolpulse.state.files import FileStateTracker

def test_record_and_suffix_path_matching():
    ft = FileStateTracker()
    ft.record_read("/repo/x/tests/test_a.py")
    assert ft.has_read("/repo/x/tests/test_a.py")          # exact
    assert ft.has_read("tests/test_a.py")                   # suffix match (legacy _paths_match)
    assert not ft.has_read("tests/test_b.py")

def test_blind_semantics_via_edited_set():
    ft = FileStateTracker()
    ft.record_edit("src/a.py")
    assert ft.has_edited("src/a.py") and not ft.has_read("src/a.py")

def test_snapshot_restore_roundtrip():
    ft = FileStateTracker()
    ft.record_read("a.py"); ft.record_edit("b.py")
    ft2 = FileStateTracker(); ft2.restore(ft.snapshot())
    assert ft2.has_read("a.py") and ft2.has_edited("b.py")

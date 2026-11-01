# tests/state/test_grammar.py
from toolpulse.state.grammar import GrammarState

def test_feed_and_current_grammar_then_trim_rebuilds():
    g = GrammarState()
    g.feed("Lt"); g.feed("P"); g.feed("Vp")
    assert g.symbols == ["Lt", "P", "Vp"]
    g.trim(1)
    assert g.symbols == ["P", "Vp"]
    from sksequitur import Production
    body = g.current_grammar()[Production(0)]
    assert len(body) == 2   # both surviving symbols "P","Vp" present after trim(1)

def test_restore_rebuild_reflects_symbols():
    from sksequitur import Production
    g = GrammarState()
    for s in ["Lt", "P", "Vp", "Lt", "P", "Vp"]:
        g.feed(s)
    g.trim(3)
    body = g.current_grammar()[Production(0)]
    assert len(body) == 3   # full re-feed: all 3 surviving symbols in start production

def test_snapshot_restore_roundtrip():
    g = GrammarState(); g.feed("A"); g.feed("B")
    g2 = GrammarState(); g2.restore(g.snapshot())
    assert g2.symbols == ["A", "B"]

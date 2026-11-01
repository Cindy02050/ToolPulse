from toolpulse.llm.stub import StubChatClient

def test_stub_returns_in_order_and_records_calls():
    c = StubChatClient(["a", "b"])
    assert c.complete("p1") == "a" and c.complete("p2", system="s") == "b"
    assert c.calls == [{"prompt": "p1", "system": None}, {"prompt": "p2", "system": "s"}]

from toolpulse.core.types import BlindActionEvent, Hint
from toolpulse.hints.sinks import CallbackSink, ListSink

def test_list_sink_collects():
    sink = ListSink()
    sink.emit([Hint(BlindActionEvent("edit", "a.py", "edit a.py"), "text")], None)
    assert len(sink.hints) == 1

def test_callback_sink_invokes():
    seen = []
    CallbackSink(lambda hints, step: seen.extend(hints)).emit(
        [Hint(BlindActionEvent("edit", "a.py", "edit a.py"), "t")], None)
    assert len(seen) == 1

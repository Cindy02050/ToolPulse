def test_exports_and_openai_isolation():
    import toolpulse
    for name in ("ToolPulse", "Action", "LabelKind", "SweAgentParser", "RepoLabeler",
                 "GenericLabeler", "MultiGranularityDetector", "TemplateHintRenderer",
                 "LLMHintRenderer", "StubChatClient", "ListSink", "CallbackSink"):
        assert hasattr(toolpulse, name), name
    assert not hasattr(toolpulse, "OpenAIChatClient")   # D17

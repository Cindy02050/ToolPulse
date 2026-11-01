def test_top_level_package_does_not_import_openai():
    import subprocess, sys, textwrap
    src = textwrap.dedent("""
        import sys, toolpulse
        assert "toolpulse.llm.openai_client" not in sys.modules
    """)
    subprocess.run([sys.executable, "-c", src], check=True)

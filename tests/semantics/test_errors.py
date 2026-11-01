from toolpulse.core.types import Action
from toolpulse.semantics.repo.errors import action_error_type, observation_error_fingerprint
from toolpulse.semantics.repo.languages import get_language


def test_syntax_error_from_observation():
    a = Action("bash-python", "python x.py", "python x.py")
    assert action_error_type(a, "  File \"x.py\", line 1\n    def f(\nSyntaxError: invalid syntax") == "syntax"

def test_import_error_and_fingerprint_stability():
    a = Action("bash-python", "python x.py", "python x.py")
    obs = "Traceback ...\nModuleNotFoundError: No module named 'foo'"
    assert action_error_type(a, obs) == "import"
    assert observation_error_fingerprint(obs, "import") == observation_error_fingerprint(obs, "import")

def test_none_when_clean():
    a = Action("bash-python", "python x.py", "python x.py")
    assert action_error_type(a, "ok output") == "none"

def test_language_registry_roundtrip_and_unknown():
    assert get_language("python").__name__.endswith("python")
    assert get_language("cpp").__name__.endswith("cpp")
    try:
        get_language("rust"); raised = False
    except ValueError:
        raised = True
    assert raised

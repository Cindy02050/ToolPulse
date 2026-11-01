import importlib
import json
import subprocess
import sys

import pytest
from toolpulse import StepObservation


def parser():
    return importlib.import_module('toolpulse.integrations.sweagent').SWEAgentActionParser()


def step(name, arguments, raw='original action'):
    return StepObservation(raw, host_context={'tool_calls': [
        {'id': 'call_1', 'function': {'name': name, 'arguments': arguments}}
    ]})


def test_editor_preserves_spaces_and_optional_arguments():
    args = {'command': 'str_replace', 'path': '/repo/a b.py', 'old_str': 'old', 'new_str': 'new'}
    parsed = parser().parse(step('str_replace_editor', json.dumps(args)))
    assert parsed.tool == 'str_replace_editor'
    assert parsed.args == args
    assert parsed.raw_action == 'original action'


def test_bash_unwraps_structured_body_for_semantics():
    parsed = parser().parse(step('bash', {'command': 'python -m pytest tests/test_x.py'}))
    assert parsed.tool == 'bash-python'
    assert parsed.args == 'python -m pytest tests/test_x.py'
    assert parsed.raw_action == 'original action'


def test_unknown_tool_keeps_structured_arguments():
    parsed = parser().parse(step('browser', {'url': 'https://example.test'}))
    assert parsed.tool == 'browser'
    assert parsed.args == {'url': 'https://example.test'}


def test_textual_tools_fall_back_to_existing_parser():
    parsed = parser().parse(StepObservation('open src/a.py'))
    assert parsed.tool == 'open' and parsed.args == {'path': 'src/a.py'}


@pytest.mark.parametrize('arguments', ['{broken', '[]'])
def test_invalid_structured_arguments_fail_explicitly(arguments):
    with pytest.raises(ValueError):
        parser().parse(step('str_replace_editor', arguments))


def test_core_and_parser_do_not_import_optional_sweagent():
    subprocess.run([sys.executable, '-c', '''
import sys
import toolpulse
from toolpulse.integrations.sweagent import SWEAgentActionParser
assert 'sweagent' not in sys.modules
'''], check=True)


def test_missing_host_has_actionable_error_without_affecting_core():
    subprocess.run([sys.executable, '-c', '''
import importlib.abc
import sys
class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'sweagent' or fullname.startswith('sweagent.'):
            raise ModuleNotFoundError('optional host unavailable', name='sweagent')
sys.meta_path.insert(0, NoHost())
import toolpulse
from toolpulse.integrations.sweagent import SWEAgentActionParser
try:
    from toolpulse.integrations.sweagent import ToolPulseSWEAgent
except ImportError as exc:
    assert 'examples/swe_agent/README.md' in str(exc)
else:
    raise AssertionError('missing optional host must be reported')
'''], check=True)

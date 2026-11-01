import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

EXAMPLE = Path(__file__).parents[3] / 'examples' / 'swe_agent' / 'run.py'


def test_example_help_does_not_require_host():
    result = subprocess.run([sys.executable, str(EXAMPLE), '--help'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--check-config' in result.stdout


def test_example_config_validates_without_starting_environment(tmp_path):
    pytest.importorskip('sweagent.agent.agents')
    spec = importlib.util.spec_from_file_location('sweagent_example', EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problem = tmp_path / 'problem.txt'
    problem.write_text('Fix the bug')
    args = module.parse_args(['--repo', str(tmp_path), '--problem-statement', str(problem), '--check-config'])
    config = module.load_config(args)
    assert config.agent.type == 'default'
    assert config.problem_statement.get_problem_statement() == 'Fix the bug'
    assert config.env.repo.path == tmp_path
    assert config.agent.tools.parse_function.type == 'function_calling'
    assert config.agent.tools.commands

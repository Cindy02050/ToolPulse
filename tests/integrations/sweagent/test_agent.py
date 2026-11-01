"""Actual SWE-agent classes with scripted model/environment; no Docker or API calls.

Skipped when the optional host is absent. CI/reproduction can put the pinned
upstream checkout on PYTHONPATH (see examples/swe_agent/README.md).
"""
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from toolpulse import StepObservation, TemplateHintProvider, ToolPulse


@pytest.fixture
def host():
    return pytest.importorskip('sweagent.agent.agents')


class ScriptedModel:
    stats = SimpleNamespace(model_dump=lambda: {})

    def __init__(self):
        self.calls = []
        self.command = 'str_replace'
        self.tool = 'str_replace_editor'
        self.path = '/repo/a b.py'
        self.counter = 0

    def query(self, history):
        self.calls.append(copy.deepcopy(history))
        self.counter += 1
        args = {'command': self.command} if self.tool == 'bash' else {
            'command': self.command, 'path': self.path,
        }
        if self.command == 'str_replace':
            args.update(old_str='old', new_str='new')
        return {'message': 'reasoning', 'tool_calls': [{
            'id': f'call_{self.counter}', 'type': 'function',
            'function': {'name': self.tool, 'arguments': json.dumps(args)},
        }]}


class Environment:
    repo = SimpleNamespace(repo_name='repo')
    name = 'stub'

    def __init__(self):
        self.commands = []
        self.output = 'actual tool output'
        self.error = None

    def communicate(self, input, **kwargs):
        self.commands.append(input)
        if self.error:
            raise self.error
        return self.output

    def set_env_variables(self, variables):
        pass

    def interrupt_session(self):
        pass


def configured(host, *, pulse=None, skip_on=None, limit=3, hint_set_name=None):
    from sweagent.agent.problem_statement import TextProblemStatement
    from sweagent.tools.tools import ToolConfig, ToolHandler
    cls = importlib.import_module('toolpulse.integrations.sweagent').ToolPulseSWEAgent
    bundle = Path(host.__file__).parents[2] / 'tools' / 'edit_anthropic'
    tools = ToolHandler(ToolConfig(
        bundles=[{'path': bundle}], enable_bash_tool=True,
        parse_function={'type': 'function_calling'},
    ))
    tools.mock_state = {'working_dir': '/repo', 'open_file': '/repo/a b.py'}
    model = ScriptedModel()
    agent = cls(
        templates=host.TemplateConfig(system_template='system', instance_template='{{problem_statement}}',
                                      next_step_template='{{observation}}', max_observation_length=100),
        tools=tools, history_processors=[], model=model, pulse=pulse,
        skip_on=skip_on, max_consecutive_skips=limit, hint_set_name=hint_set_name,
    )
    agent._env = Environment()
    agent._problem_statement = TextProblemStatement(text='fix bug', id='test')
    return agent


def test_pre_skip_keeps_pair_and_next_context_without_execution(host):
    agent = configured(host)
    step = agent.step()
    assert agent._env.commands == []
    assert agent.pulse.state.total_actions_seen == 0
    assert not step.done and step.execution_time == 0
    assert step.extra_info['toolpulse']['execution_status'] == 'skipped'
    assert step.extra_info['toolpulse']['events'][0]['path'] == '/repo/a b.py'
    assert agent.history[-2]['tool_calls'][0]['id'] == 'call_1'
    assert agent.history[-1]['tool_call_ids'] == ['call_1']
    assert agent.history[-1]['role'] == 'tool'
    assert 'not executed' in agent.history[-1]['content']
    assert '<tool_pulse>' in agent.history[-1]['content']
    json.dumps(agent.get_trajectory_data())
    agent.model.command = 'view'
    agent.step()
    assert '<tool_pulse>' in agent.model.calls[-1][-1]['content']
    assert len(agent._env.commands) == agent.pulse.state.total_actions_seen == 1
    agent.model.command = 'str_replace'
    agent.step()
    assert len(agent._env.commands) == agent.pulse.state.total_actions_seen == 2


def test_warn_only_executes_and_delivers_pre_hint(host):
    agent = configured(host, skip_on=set())
    step = agent.step()
    assert len(agent._env.commands) == agent.pulse.state.total_actions_seen == 1
    assert step.extra_info['toolpulse']['execution_status'] == 'executed'
    assert 'before inspecting' in agent.history[-1]['content']
    assert step.observation == 'actual tool output'


def test_pre_skip_survives_dropped_llm_hints(host):
    class Drop:
        def provide(self, events, ctx):
            return []
    agent = configured(host, pulse=ToolPulse.for_swe_repo(hint_provider=Drop()))
    step = agent.step()
    assert step.extra_info['toolpulse']['execution_status'] == 'skipped'
    assert agent._env.commands == []
    assert 'before inspecting' in agent.history[-1]['content']


def test_repeated_pre_skips_end_at_explicit_limit(host):
    agent = configured(host, limit=2)
    assert not agent.step().done
    last = agent.step()
    assert last.done and last.exit_status == 'toolpulse_skip_limit'
    assert agent._env.commands == []
    assert agent.pulse.state.total_actions_seen == 0


def test_raw_output_is_used_for_post_and_hint_survives_truncation(host):
    agent = configured(host)
    agent.model.tool = 'bash'
    agent.model.command = 'python run.py'
    agent._env.output = 'x' * 200
    for _ in range(3):
        step = agent.step()
    assert step.observation == 'x' * 200
    assert agent.pulse.state.actions[-1].observation == 'x' * 200
    assert '3 consecutive' in agent.history[-1]['content']
    assert agent.pulse.state.actions[-1].action.tool == 'bash-python'
    assert len(agent._env.commands) == agent.pulse.state.total_actions_seen == 3
    json.dumps(agent.get_trajectory_data())


def test_json_mode_is_actual_json_tool_content(host):
    pulse = ToolPulse.for_swe_repo(hint_provider=TemplateHintProvider(hint_set_name='different_message_type'))
    agent = configured(host, pulse=pulse)
    agent.step()
    content = json.loads(agent.history[-1]['content'])
    assert 'not executed' in content['observation']
    assert 'before inspecting' in content['hint']
    assert agent.history[-1]['tool_call_ids'] == ['call_1']


def test_native_tool_retry_is_recorded_and_preserves_call_metadata(host):
    agent = configured(host)
    agent.model.tool = 'bash'
    agent.model.command = 'python run.py'
    original_query = agent.model.query
    def query(history):
        output = original_query(history)
        agent._env.output = 'first output\n' + host.RETRY_WITH_OUTPUT_TOKEN if agent.model.counter == 1 else 'second output'
        return output
    agent.model.query = query
    agent.step()
    assert len(agent._env.commands) == agent.pulse.state.total_actions_seen == 2
    retry_history = agent.model.calls[1]
    assert retry_history[-2]['tool_calls'][0]['id'] == 'call_1'
    assert retry_history[-1]['tool_call_ids'] == ['call_1']
    assert retry_history[-1]['role'] == 'tool'
    assert 'first output' in retry_history[-1]['content']


def test_setup_resets_task_hints_file_knowledge_and_skip_counter(host, tmp_path):
    agent = configured(host)
    agent.step()
    agent.pulse.state.files.record_read('old.py')
    agent.tools.install = lambda env: None
    agent.setup(agent._env, agent._problem_statement, output_dir=tmp_path)
    assert agent.pulse.state.total_actions_seen == 0
    assert not agent.pulse.state.files.has_read('old.py')
    assert agent.pulse.hints == []
    assert agent.pulse.task_description == 'fix bug'
    assert not agent.step().done


@pytest.mark.parametrize('limit', [0, -1, 1.5, True])
def test_invalid_skip_budget_rejected(host, limit):
    with pytest.raises(ValueError):
        configured(host, limit=limit)


def test_native_retry_clips_before_appending_feedback(host):
    agent = configured(host)
    agent.model.tool = 'bash'
    agent.model.command = 'python run.py'
    original = agent.model.query
    def query(history):
        output = original(history)
        agent._env.output = ('x' * 1000 + host.RETRY_WITH_OUTPUT_TOKEN) if agent.model.counter == 1 else 'done'
        return output
    agent.model.query = query
    agent.step()
    content = agent.model.calls[1][-1]['content']
    assert len(content) < 200 and '<response clipped>' in content


def test_text_retry_keeps_json_shape_and_saved_feedback(host):
    pulse = ToolPulse.for_swe_repo(hint_provider=TemplateHintProvider(hint_set_name='different_message_type'))
    agent = configured(host, pulse=pulse)
    step = host.StepOutput(output='python run.py', action='python run.py', observation='actual output', extra_info={
        'toolpulse': {'hints': [{'event': {'type': 'custom'}, 'text': 'saved feedback'}]}
    })
    agent._last_action_step = step
    history = agent.get_model_requery_history('{{observation}}', **step.to_template_format_dict())
    assert json.loads(history[-1]['content']) == {'observation': 'actual output', 'hint': 'saved feedback'}
    assert history[-1]['role'] == 'user'


def test_from_config_keeps_adapter_options_without_model_request(host):
    from sweagent.agent.agents import DefaultAgentConfig
    cls = importlib.import_module('toolpulse.integrations.sweagent').ToolPulseSWEAgent
    config = DefaultAgentConfig(name='custom', model={'name': 'human'})
    pulse = ToolPulse.for_swe_repo()
    agent = cls.from_config(config, pulse=pulse, skip_on=set(), max_consecutive_skips=5)
    assert agent.pulse is pulse and agent.skip_on == frozenset()
    assert agent.max_consecutive_skips == 5 and agent.name == 'custom'


def test_syntax_rejection_is_not_a_toolpulse_execution(host):
    from swerex.exceptions import BashIncorrectSyntaxError
    agent = configured(host)
    agent.model.tool = 'bash'
    agent.model.command = 'python broken.py'
    agent._env.error = BashIncorrectSyntaxError('syntax invalid')
    step = host.StepOutput(action='python broken.py')
    with pytest.raises(BashIncorrectSyntaxError):
        agent.handle_action(step)
    assert agent.pulse.state.total_actions_seen == 0
    assert step.extra_info['toolpulse']['execution_status'] == 'not_executed'


def test_terminal_timeout_is_still_recorded_once(host):
    from swerex.exceptions import CommandTimeoutError
    agent = configured(host)
    agent.model.tool = 'bash'
    agent.model.command = 'python long.py'
    agent._env.error = CommandTimeoutError('timed out')
    agent._n_consecutive_timeouts = agent.tools.config.max_consecutive_execution_timeouts - 1
    step = host.StepOutput(action='python long.py')
    with pytest.raises(CommandTimeoutError):
        agent.handle_action(step)
    assert agent.pulse.state.total_actions_seen == 1
    assert agent.pulse.state.actions[-1].label.error.kind == 'runtime'


def test_skipped_call_serializes_through_actual_model_provider_format(host):
    from sweagent.agent.models import LiteLLMModel
    agent = configured(host)
    agent.step()
    model = SimpleNamespace(config=SimpleNamespace(convert_system_to_user=False), logger=agent.logger)
    messages = LiteLLMModel._history_to_messages(model, agent.messages)
    assert messages[-2]['tool_calls'][0]['id'] == 'call_1'
    assert messages[-1]['tool_call_id'] == 'call_1'
    assert '<tool_pulse>' in messages[-1]['content']

"""DefaultAgent adapter for official SWE-agent revision 3ea751c.

The host package is intentionally optional. This module owns execution policy
and message delivery; ToolPulse's detector does not decide whether a tool runs.
"""
from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

try:
    from sweagent.agent.agents import DefaultAgent
    from sweagent.agent.hooks.abstract import AbstractAgentHook
except ModuleNotFoundError as exc:
    if exc.name == "sweagent" or (exc.name or "").startswith("sweagent."):
        raise ImportError(
            "ToolPulseSWEAgent requires official SWE-agent. See examples/swe_agent/README.md "
            "for the supported revision and installation instructions."
        ) from exc
    raise

from swerex.exceptions import BashIncorrectSyntaxError, CommandTimeoutError
from jinja2 import Template

from toolpulse.core.types import Hint, HintContext, PulseEvent, StepObservation
from toolpulse.hints.template import TemplateHintRenderer
from toolpulse.integrations.sweagent.parser import SWEAgentActionParser
from toolpulse.middleware import ToolPulse
from toolpulse.semantics.repo.labeler import RepoLabeler


@dataclass(frozen=True)
class _StoredEvent(PulseEvent):
    """Read JSON-safe saved feedback without requiring the original event class."""
    payload: dict[str, Any]

    @property
    def type(self) -> str:
        return self.payload["type"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.payload)


class _ExecutionHook(AbstractAgentHook):
    def __init__(self, agent: ToolPulseSWEAgent) -> None:
        self.agent = agent

    def on_action_started(self, *, step) -> None:
        step.extra_info.setdefault("toolpulse", {})["execution_status"] = "started"

    def on_action_executed(self, *, step) -> None:
        # This also runs for tool results that subsequently request a native
        # requery; on_step_done would miss those executed attempts.
        self.agent._record_execution(step)


class ToolPulseSWEAgent(DefaultAgent):
    """SWE-agent DefaultAgent with pre gating and executed-only post analysis.

    Each agent owns one pulse/session. Passing a pulse installs a structured-call
    parser around its existing parser. A pulse must not be shared across agents.
    """

    def __init__(self, *, pulse: ToolPulse | None = None,
                 skip_on: Iterable[str] | None = None, max_consecutive_skips: int = 3,
                 hint_set_name: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._configure_pulse(pulse, skip_on, max_consecutive_skips, hint_set_name)
        self._active_input: StepObservation | None = None
        self._last_action_step = None
        self.add_hook(_ExecutionHook(self))

    def _configure_pulse(self, pulse, skip_on, limit, hint_set_name) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("max_consecutive_skips must be a positive integer")
        if isinstance(skip_on, str):
            raise ValueError("skip_on must be a collection of event type strings")
        self.pulse = pulse if pulse is not None else ToolPulse(
            parser=SWEAgentActionParser(), labeler=RepoLabeler()
        )
        if not isinstance(self.pulse.parser, SWEAgentActionParser):
            self.pulse.parser = SWEAgentActionParser(fallback=self.pulse.parser)
        self.skip_on = frozenset({"blind_action"} if skip_on is None else skip_on)
        if any(not isinstance(value, str) for value in self.skip_on):
            raise ValueError("skip_on entries must be event type strings")
        self.max_consecutive_skips = limit
        self.hint_set_name = hint_set_name
        self._consecutive_skips = 0

    @classmethod
    def from_config(cls, config, *, pulse: ToolPulse | None = None,
                    skip_on: Iterable[str] | None = None, max_consecutive_skips: int = 3,
                    hint_set_name: str | None = None):
        if config.type != "default":
            raise ValueError("ToolPulseSWEAgent supports DefaultAgentConfig (type: default) only")
        agent = super().from_config(config)
        agent.name = config.name
        agent._configure_pulse(pulse, skip_on, max_consecutive_skips, hint_set_name)
        return agent

    def setup(self, env, problem_statement, output_dir=None) -> None:
        self.pulse.reset()
        self._consecutive_skips = 0
        self._active_input = None
        self._last_action_step = None
        # DefaultAgent normally creates a new object per attempt; also make
        # explicitly reusing this adapter for a new task safe.
        self.history.clear()
        self._trajectory.clear()
        self._n_consecutive_timeouts = 0
        self._total_execution_time = 0.0
        kwargs = {} if output_dir is None else {"output_dir": output_dir}
        super().setup(env, problem_statement, **kwargs)
        self.pulse.set_task_description(self._problem_statement.get_problem_statement())

    def forward(self, history):
        self._last_action_step = None
        return super().forward(history)

    def handle_action(self, step):
        self._last_action_step = step
        # Preserve the host's blocklist and explicit exit semantics.
        if self.tools.should_block_action(step.action) or step.action.strip() == "exit":
            return super().handle_action(step)

        state = self.tools.get_state(env=self._env)
        pre = StepObservation(
            raw_action=step.action, thought=step.thought,
            host_context={**state, "tool_calls": step.tool_calls},
        )
        inspection = self.pulse.inspect_action(pre)
        hints = list(inspection.hints)
        blocked = [event for event in inspection.events if event.type in self.skip_on]
        # LLM rendering may fail softly. Policy always uses events and a fixed
        # fallback makes the reason for a refusal visible to the next query.
        missing = [event for event in blocked if not any(h.event == event for h in hints)]
        if missing:
            fallback = TemplateHintRenderer().render(missing, HintContext(
                task_description=self.pulse.task_description, step_observation="",
                recent_trajectory=self.pulse.state.recent_actions(3),
            ))
            # Custom event types may not have built-in templates.
            if not fallback:
                fallback = [Hint(event, f"ToolPulse pre-check rejected event: {event.type}") for event in missing]
            hints.extend(fallback)
            self.pulse.hint_sink.emit(fallback, pre)
        step.extra_info["toolpulse"] = {
            "execution_status": "pending",
            "events": [event.to_dict() for event in inspection.events],
            "hints": [self._hint_data(hint) for hint in hints],
        }
        if blocked:
            self._consecutive_skips += 1
            step.state = state
            step.execution_time = 0.0
            step.done = self._consecutive_skips >= self.max_consecutive_skips
            step.observation = "Tool call was not executed: rejected by ToolPulse pre-check."
            step.extra_info["toolpulse"]["execution_status"] = "skipped"
            if step.done:
                step.exit_status = "toolpulse_skip_limit"
                step.observation += f" Stopping after {self._consecutive_skips} consecutive rejected calls."
            return step

        self._consecutive_skips = 0
        self._active_input = pre
        try:
            return super().handle_action(step)
        except BashIncorrectSyntaxError:
            step.extra_info["toolpulse"]["execution_status"] = "not_executed"
            raise
        except CommandTimeoutError:
            # On the terminal consecutive-timeout path, upstream raises before
            # on_action_executed. It still represents a real execution attempt.
            if step.extra_info["toolpulse"]["execution_status"] == "started":
                step.observation = "Tool execution timed out."
                self._record_execution(step)
            raise
        finally:
            self._active_input = None

    @staticmethod
    def _hint_data(hint: Hint) -> dict[str, Any]:
        return {"event": hint.event.to_dict(), "text": hint.text}

    def _record_execution(self, step) -> None:
        if self._active_input is None:
            return
        metadata = step.extra_info["toolpulse"]
        if metadata["execution_status"] == "executed":
            return
        raw = StepObservation(
            raw_action=step.action, thought=step.thought, observation=step.observation,
            execution_time=step.execution_time, host_context=self._active_input.host_context,
        )
        hints = self.pulse.observe_step(raw)
        metadata["execution_status"] = "executed"
        metadata["events"].extend(hint.event.to_dict() for hint in hints)
        metadata["hints"].extend(self._hint_data(hint) for hint in hints)

    @staticmethod
    def _action_message(step, agent: str) -> dict[str, Any]:
        return {
            "role": "assistant", "content": step.output, "thought": step.thought,
            "action": step.action, "agent": agent, "tool_calls": deepcopy(step.tool_calls),
            "message_type": "action", "thinking_blocks": deepcopy(step.thinking_blocks),
        }

    def _observation_message(self, step, content: str) -> dict[str, Any]:
        message = {"role": "user", "content": content, "agent": self.name, "message_type": "observation"}
        if step.tool_call_ids:
            if len(step.tool_call_ids) != 1:
                raise ValueError("SWE-agent integration expects one tool-call ID")
            message.update(role="tool", tool_call_ids=list(step.tool_call_ids))
        return message

    def _assemble(self, step, observation: str) -> str:
        hints = [Hint(_StoredEvent(item["event"]), item["text"])
                 for item in step.extra_info.get("toolpulse", {}).get("hints", [])]
        return self.pulse.assemble_observation(observation, hints, hint_set_name=self.hint_set_name)

    def _present_observation(self, step, rendered_error: str | None = None) -> str:
        name = self.hint_set_name or getattr(self.pulse.hint_renderer, "hint_set_name", "remind_only")
        limit = self.templates.max_observation_length
        if rendered_error is not None or name == "different_message_type":
            observation = step.observation if rendered_error is None else rendered_error
            if len(observation) > limit:
                observation = observation[:limit] + "<response clipped>"
        else:
            if not step.observation.strip():
                template = self.templates.next_step_no_output_template
            elif len(step.observation) > limit:
                template = self.templates.next_step_truncated_observation_template
            else:
                template = self.templates.next_step_template
            values = {**step.state, "observation": step.observation,
                      "max_observation_length": limit, "elided_chars": max(0, len(step.observation) - limit)}
            observation = Template(template).render(**self._get_format_dict(**values))
        # Feedback is attached AFTER host truncation/template selection. Raw
        # step.observation remains intact for the trajectory and post detector.
        return self._assemble(step, observation)

    def add_step_to_history(self, step) -> None:
        self._append_history(self._action_message(step, self.name))
        self._append_history(self._observation_message(step, self._present_observation(step)))

    def get_model_requery_history(self, error_template: str, *, output: str, **kwargs):
        step = self._last_action_step
        if step is None:
            history = super().get_model_requery_history(error_template, output=output, **kwargs)
            content = history[-1]["content"]
            limit = self.templates.max_observation_length
            if len(content) > limit:
                content = content[:limit] + "<response clipped>"
            history[-1]["content"] = self.pulse.assemble_observation(content, [], hint_set_name=self.hint_set_name)
            return history
        # Upstream's temporary assistant/user requery drops function-call IDs.
        # Preserve the same pairing as a regular tool response for native errors.
        observation = Template(error_template).render(**self._get_format_dict(**kwargs))
        return self.messages + [
            self._action_message(step, self.name),
            self._observation_message(step, self._present_observation(step, rendered_error=observation)),
        ]

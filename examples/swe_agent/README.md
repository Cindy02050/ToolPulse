# ToolPulse + official SWE-agent

[English](README.md) | [简体中文](README.zh-CN.md)

The reusable integration lives in `toolpulse.integrations.sweagent`. This example only loads configuration, creates the adapter, and manages the environment. It does not patch SWE-agent at runtime.

Supported/tested upstream: official [SWE-agent commit `3ea751c087f32b16e039a2233dd6eefecef325d5`](https://github.com/SWE-agent/SWE-agent/tree/3ea751c087f32b16e039a2233dd6eefecef325d5). The host requires Python 3.11+, although ToolPulse core supports Python 3.10+. The adapter currently supports `DefaultAgentConfig`; `RetryAgent` and `ShellAgent` are not supported. Tests use the actual upstream agent, parser and message lifecycle with scripted model/environment objects; Docker and hosted model execution are separate runtime checks.

## Install

In one Python 3.11+ environment, install the official source checkout and ToolPulse. An editable SWE-agent checkout also provides its tool bundles. The older PyPI `sweagent` release does not provide the API targeted here.

```bash
git clone https://github.com/SWE-agent/SWE-agent.git /path/to/SWE-agent
git -C /path/to/SWE-agent checkout 3ea751c087f32b16e039a2233dd6eefecef325d5
python -m pip install -e /path/to/SWE-agent
python -m pip install -e '/path/to/ToolPulse[dev]'
```

Run the commands below from the ToolPulse repository root. Use a clean, committed local Git repository as the target; SWE-agent copies it into its environment. Describe the task in a UTF-8 text file. The supplied config uses an interactive human model by default, so it does not silently select a paid model. Override `--model` and configure the corresponding credentials to use a hosted model.

## Validate and run

```bash
python examples/swe_agent/run.py \
  --repo /path/to/target-repo \
  --problem-statement /path/to/task.txt \
  --check-config

# Requires a running Docker service. Omit --model for interactive human mode.
python examples/swe_agent/run.py \
  --repo /path/to/target-repo \
  --problem-statement /path/to/task.txt \
  --model YOUR_MODEL_NAME \
  --hint-set remind_and_guide \
  --output-dir trajectories/toolpulse
```

`--check-config` validates the YAML, tool bundles and task fields without constructing an environment or querying a model. Customize the Docker image and setup commands in `config.yaml` for the target repository's dependencies. `--hint-set different_message_type` delivers a JSON string containing `observation` and newline-joined `hint` fields; it remains the content of the paired tool response, not a different API role.

The example writes the normal SWE-agent trajectory plus `toolpulse.json` with the adapter's policy settings. It does not open PRs or apply the result to the source repository. The Docker environment is closed on success and exceptions.

## Reuse the adapter directly

```python
from toolpulse import TemplateHintRenderer, ToolPulse
from toolpulse.integrations.sweagent import ToolPulseSWEAgent

pulse = ToolPulse.for_swe_repo(
    hint_renderer=TemplateHintRenderer(hint_set_name="remind_only")
)
agent = ToolPulseSWEAgent.from_config(
    config.agent,
    pulse=pulse,
    skip_on={"blind_action"},
    max_consecutive_skips=3,
)
agent.run(env=env, problem_statement=problem_statement, output_dir=output_dir)
```

Each agent must have its own ToolPulse instance. The adapter wraps the pulse's parser to consume native `tool_calls` directly, preserving quoted editor paths and unwrapping the bash command for semantic labeling. Text-only tool syntax uses the original parser as a fallback and retains its supported-syntax limits.

## Pre, execution and feedback

- Pre policy uses `ActionInspection.events`, independently of LLM-rendered text. Missing rejection hints receive a fixed-template fallback. `observe_action()` remains compatible and still returns `list[Hint]`.
- By default a Blind Command is not executed. Its original call ID receives an explicit refusal response containing the hint, allowing the model to inspect the file and retry. The skipped proposal is saved in the host trajectory but is not passed to ToolPulse post analysis.
- The third consecutive refusal ends the run with `exit_status=toolpulse_skip_limit` by default. Set `--max-consecutive-skips N` to change the limit, or `--warn-only` / `skip_on=set()` to deliver hints without blocking execution. A proposal accepted by pre resets the consecutive refusal counter.
- Actual execution results are recorded once, including completed attempts that trigger SWE-agent's native retry mechanism and terminal tool timeouts. Bash syntax errors rejected before execution are not recorded as executions. Other host/environment exceptions retain the upstream handling; there may be no completed observation to analyze.
- Observation text is left raw in the trajectory and passed raw to post analysis. Model-facing output is truncated/formatted first, then hints are attached. In JSON mode the displayed `observation` is also clipped when it exceeds the host limit; the unmodified output remains in the trajectory.
- For successfully parsed calls, function-call IDs and thinking blocks are retained for both ordinary and native-retry messages. Responses rejected by the host parser before a valid call is available retain the host's format-error handling. Metadata in `step.extra_info["toolpulse"]` is JSON-safe and includes execution status, detected/rendered events and hint texts. Post event metadata includes events for delivered hints; events dropped by the post renderer are not independently exposed.
- `setup()` resets ToolPulse, prior host history, trajectory and execution counters before a new task. This adapter does not add support for the separate `RetryAgent` factory.

The adapter does not fix SWE-agent's general native retry policy; the pre-refusal budget is independent of upstream format/tool retry limits. Message history processors still control how old observations are retained.

## Tests

```bash
python -m pytest tests/integrations/sweagent tests/test_action_inspection.py
```

The parser/isolation tests run without SWE-agent. Host integration tests skip when the optional host is absent. To exercise exactly the supported checkout without installing it, prepend it to `PYTHONPATH` in an environment with its dependencies installed:

```bash
PYTHONPATH=/path/to/SWE-agent:/path/to/ToolPulse/src \
  python -m pytest tests/integrations/sweagent
```

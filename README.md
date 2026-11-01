# ToolPulse

[English](README.md) | [简体中文](README.zh-CN.md)

**State-flow-tracking online tool-use assistance for task-oriented agents.**

ToolPulse is a middleware support layer for autonomous tool use. It tracks an agent's execution context and temporal tool-use patterns across interactions, examining proposed calls before execution and tool feedback before the agent continues. Its evolving state helps identify clumsy tool-use behaviors and tool-use detours in the context of the agent's working rhythm.

When assistance is warranted, ToolPulse provides a cue, offers context-specific guidance, or lets the host intercept an insufficiently grounded call. Like a weightlifting spotter, it lends a hand when needed while the agent remains responsible for carrying the task forward.

## Quick start

Requires **Python 3.10+**. From the repository root:

```bash
python -m pip install -e .
python examples/minimal_react/run.py
```

This runs a complete minimal ReAct loop with two in-memory tools. After installation, the demo needs no API key, model service, network access, Docker, or SWE-agent.

The seven scripted actions demonstrate Blind Command, Failure Inertia, and Calling Repetition, followed by a successful correction. The output includes:

```text
Tool-use notice: You tried to edit note.txt using file before inspecting the file in the current task.
Tool-use notice: You received test_failure error again from check without taking an effective recovery action after the previous error.
Tool-use notice: You called check with exactly the same arguments in 3 consecutive steps.
...
Finished
```

Decisions are scripted for reproducibility; they do not change in response to hints. Tool results come from actual operations on the in-memory files. See the [minimal ReAct example](examples/minimal_react/README.md) for the full walkthrough.

## How it works

ToolPulse maintains execution state across interactions and checks tool use at two points:

```text
Agent proposes a tool call
  → Pre-check using current context
  → Host executes or intercepts the call
  → Post-analysis of executed tool feedback
  → Assistance is added to the next agent input
```

The current detector covers five behaviors:

| Behavior | Signal |
|---|---|
| Blind Command | Editing a file before inspecting it in the current task |
| Calling Repetition | Consecutive calls with the same action and arguments |
| Failure Inertia | Recurring failures without an intervening recovery signal |
| Functional Cycle | Repeated semantic action sequences |
| Strategic Fixation | Highly similar behavior across consecutive interaction windows |

The framework supplies action syntax and semantics; ToolPulse supplies shared state tracking, detection, and assistance generation. The host controls execution and delivers the feedback to the agent.

## Forms of assistance

ToolPulse's assistance follows three forms from the method:

| Form | Purpose | Mechanism in this implementation |
|---|---|---|
| **Verbal cueing** | Briefly draw attention to a behavior or guide the next move | Template hints: `remind_only` and `remind_and_guide` |
| **Visual cueing** | Make textual feedback easier to distinguish through structured presentation | `different_message_type`: a JSON string with separate `observation` and `hint` fields |
| **Tactile spotting** | Offer context-specific suggestions through a fast auxiliary language model | `LLMHintProvider` with a caller-configured model client |

Visual cueing here uses structured text. Tactile spotting is the spotter metaphor for auxiliary-model assistance; model choice and latency depend on the configured service. Both examples use template hints by default, without an auxiliary model call.

To try structured feedback:

```bash
python examples/minimal_react/run.py --hint-set different_message_type
```

For auxiliary-model assistance, install the optional client dependency with `python -m pip install -e '.[llm]'` and configure the provider and client as described in the [implementation guide](docs/implementation-guide.md).

## Examples

| Example | What it demonstrates | Requirements |
|---|---|---|
| [Minimal ReAct](examples/minimal_react/README.md) | A directly editable loop, its own action parser and semantic vocabulary, and explicit pre/post integration | ToolPulse only; scripted decisions |
| [SWE-agent](examples/swe_agent/README.md) | A reusable adapter for an existing agent's execution and message lifecycle | Python 3.11+, the documented official SWE-agent revision, and Docker for task execution |

The SWE-agent example defaults to interactive `human` mode without an API key. Automated model use needs a configured model service and any required credentials. Its `--check-config` mode validates configuration without starting Docker or querying a model. See its README for installation and launch commands.

## Integrating another framework

A new integration supplies an **action parser** and a **semantic labeler**, including its label vocabulary, tool-use kinds, error fingerprints, and relevant context such as file reads and edits. The minimal ReAct implementation places these components in `src/toolpulse/parsing/minimal_react.py` and `src/toolpulse/semantics/minimal_react/`.

In the host loop, call `inspect_action()` before execution and `observe_step()` once for each executed action. Use `assemble_observation()` to combine the returned hints with tool feedback for the next agent input, and reset the session for a new task. The host may act on pre-check events to intercept a call or continue with a warning.

The [minimal ReAct walkthrough](examples/minimal_react/README.md) shows all of these steps. The [implementation guide](docs/implementation-guide.md) covers custom parsers, labelers, detectors, providers, and sinks.

## Repository structure

```text
ToolPulse/
├── src/toolpulse/        # Reusable middleware and framework integrations
│   ├── parsing/         # Framework action parsers
│   ├── semantics/       # Semantic vocabularies, labels, and error classification
│   ├── integrations/    # Adapters for existing agent frameworks
│   └── ...              # Shared state, detectors, hints, and optional model clients
├── examples/
│   ├── minimal_react/   # A directly editable, scripted ReAct loop
│   └── swe_agent/       # Configuration and runner for official SWE-agent
├── tests/               # Unit, integration, and compatibility regression tests
├── docs/                # Implementation guide and design documents
└── pyproject.toml       # Package metadata and dependencies
```

Framework parsers and semantics live in `src`; examples provide the host loop or runner that uses them. Both examples include English and Chinese READMEs.

## Scope and development

Detection is heuristic: a flagged pattern calls for contextual judgment. This implementation includes one multi-granularity detector, a minimal ReAct semantic vocabulary, and repository-oriented semantics for Python, Java, and C++. The SWE-agent adapter supports the documented `DefaultAgent` revision. The examples demonstrate integration; they are not a benchmark of task performance.

Install development dependencies and run the tests:

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

Tests requiring SWE-agent skip when the optional host is absent. The [implementation guide](docs/implementation-guide.md) preserves the original README's architecture, API contracts, ToolFamiliar code mapping, and intentional compatibility differences.

## License

ToolPulse is released under the [MIT License](LICENSE). Copyright notices and license terms for adapted upstream code are preserved in [Third-party notices](THIRD_PARTY_NOTICES.md).

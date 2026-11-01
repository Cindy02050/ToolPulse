"""Run the reusable ToolPulse adapter on a local Git repository in SWE-agent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--repo", type=Path, required=True, help="Local Git repository to copy into the container")
    parser.add_argument("--problem-statement", type=Path, required=True, help="UTF-8 file describing the task")
    parser.add_argument("--model", help="Override agent.model.name; default config uses interactive human mode")
    parser.add_argument("--output-dir", type=Path, default=Path("trajectories/toolpulse"))
    parser.add_argument("--hint-set", default="remind_only", choices=[
        "remind_only", "remind_and_guide", "different_message_type",
    ])
    parser.add_argument("--language", default="python", choices=["python", "java", "cpp"])
    parser.add_argument("--warn-only", action="store_true", help="Deliver pre feedback without blocking tools")
    parser.add_argument("--max-consecutive-skips", type=int, default=3)
    parser.add_argument("--check-config", action="store_true", help="Validate only; do not start Docker or query a model")
    args = parser.parse_args(argv)
    if args.max_consecutive_skips < 1:
        parser.error("--max-consecutive-skips must be >= 1")
    return args


def load_config(args):
    from sweagent.run.run_single import RunSingleConfig

    data = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Example config must be a YAML mapping")
    data.setdefault("env", {})["repo"] = {"type": "local", "path": str(args.repo.resolve())}
    data["problem_statement"] = {
        "type": "text", "text": args.problem_statement.read_text(encoding="utf-8"),
    }
    data["output_dir"] = str(args.output_dir.resolve())
    if args.model:
        data["agent"]["model"]["name"] = args.model
    config = RunSingleConfig.model_validate(data)
    if config.agent.type != "default":
        raise ValueError("This example supports agent.type: default only")
    if config.actions.open_pr or config.actions.apply_patch_locally:
        raise ValueError("This example saves trajectories only; external run actions are not supported")
    return config


def main(argv=None) -> int:
    args = parse_args(argv)
    config = load_config(args)
    if args.check_config:
        print("Configuration valid. No environment or model was started.")
        return 0

    from sweagent.environment.swe_env import SWEEnv
    from sweagent.utils.config import load_environment_variables
    from toolpulse import TemplateHintRenderer, ToolPulse
    from toolpulse.integrations.sweagent import ToolPulseSWEAgent

    load_environment_variables(config.env_var_path)
    pulse = ToolPulse.for_swe_repo(
        language=args.language, hint_renderer=TemplateHintRenderer(hint_set_name=args.hint_set),
    )
    agent = ToolPulseSWEAgent.from_config(
        config.agent, pulse=pulse, skip_on=set() if args.warn_only else {"blind_action"},
        max_consecutive_skips=args.max_consecutive_skips,
    )
    agent.replay_config = config
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "toolpulse.json").write_text(json.dumps({
        "hint_set_name": args.hint_set, "language": args.language,
        "skip_on": sorted(agent.skip_on), "max_consecutive_skips": args.max_consecutive_skips,
    }, indent=2), encoding="utf-8")
    env = SWEEnv.from_config(config.env)
    try:
        env.start()
        agent.run(env=env, problem_statement=config.problem_statement, output_dir=config.output_dir)
    finally:
        env.close()
    print(f"Trajectory saved under {config.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

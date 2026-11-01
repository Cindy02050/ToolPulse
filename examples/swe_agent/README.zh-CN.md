# ToolPulse + 官方 SWE-agent

[English](README.md) | [简体中文](README.zh-CN.md)

可复用的接入实现位于 `toolpulse.integrations.sweagent`。本示例只负责加载配置、创建 adapter 和管理环境，不会在运行时修改 SWE-agent。

支持并测试的上游版本：官方 [SWE-agent commit `3ea751c087f32b16e039a2233dd6eefecef325d5`](https://github.com/SWE-agent/SWE-agent/tree/3ea751c087f32b16e039a2233dd6eefecef325d5)。宿主要求 Python 3.11+，ToolPulse 核心支持 Python 3.10+。adapter 当前支持 `DefaultAgentConfig`，不支持 `RetryAgent` 和 `ShellAgent`。测试使用真实上游 agent、parser 和消息生命周期，模型与环境由预设对象替代；Docker 与真实模型执行需要单独进行运行验证。

## 安装

在同一个 Python 3.11+ 环境中安装官方源码和 ToolPulse。以 editable 方式安装 SWE-agent 源码也会提供运行所需的工具包。较旧的 PyPI `sweagent` 版本不提供本接入所需的 API。

```bash
git clone https://github.com/SWE-agent/SWE-agent.git /path/to/SWE-agent
git -C /path/to/SWE-agent checkout 3ea751c087f32b16e039a2233dd6eefecef325d5
python -m pip install -e /path/to/SWE-agent
python -m pip install -e '/path/to/ToolPulse[dev]'
```

以下命令均从 ToolPulse 仓库根目录执行。目标应是已提交且工作区干净的本地 Git 仓库，SWE-agent 会将它复制到执行环境中。用 UTF-8 文本文件描述任务。默认配置使用交互式 human 模式，不会自动选择付费模型。使用真实模型时，通过 `--model` 指定模型并配置相应凭据。

## 验证配置与运行

```bash
python examples/swe_agent/run.py \
  --repo /path/to/target-repo \
  --problem-statement /path/to/task.txt \
  --check-config

# 需要运行中的 Docker 服务。不传 --model 则使用交互式 human 模式。
python examples/swe_agent/run.py \
  --repo /path/to/target-repo \
  --problem-statement /path/to/task.txt \
  --model YOUR_MODEL_NAME \
  --hint-set remind_and_guide \
  --output-dir trajectories/toolpulse
```

`--check-config` 验证 YAML、工具包和任务字段，不会创建执行环境或调用模型。请按目标仓库的依赖调整 `config.yaml` 中的 Docker 镜像与初始化命令。`--hint-set different_message_type` 返回包含 `observation` 与 `hint` 字段的 JSON 字符串，多条提示用换行连接；它仍是对应工具响应的内容，不是另一个 API 消息角色。

示例保存 SWE-agent 的常规轨迹，以及记录 adapter 策略配置的 `toolpulse.json`。它不会创建 PR，也不会把结果应用回原始仓库。无论成功还是发生异常，Docker 环境都会关闭。

## 直接复用 adapter

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

每个 agent 应拥有独立的 ToolPulse 实例。adapter 包装 pulse 的 parser，直接处理原生 `tool_calls`，保留编辑器路径中的引号语义，并提取 bash 命令用于语义解析。纯文本工具语法回退到原 parser，沿用其支持的语法范围。

## 执行前检查、工具执行与反馈

- pre 策略根据 `ActionInspection.events` 判断，独立于 LLM 渲染的提示文本。缺少拒绝提示时，使用固定模板补充。`observe_action()` 保持兼容，仍返回 `list[Hint]`。
- 默认不执行 Blind Command 调用，而是向原调用 ID 返回带提示的明确拒绝响应，让模型可以先读取文件再重试。被跳过的提案保存在宿主轨迹中，但不进入 ToolPulse 的 post 分析。
- 默认连续第三次拒绝时，以 `exit_status=toolpulse_skip_limit` 结束。可用 `--max-consecutive-skips N` 修改上限，或用 `--warn-only` / `skip_on=set()` 只提醒而不拦截。pre 接受一次提案后，连续拒绝计数归零。
- 实际执行结果只记录一次，包括触发 SWE-agent 原生重试的已完成尝试，以及达到终止条件的工具超时。执行前被拒绝的 bash 语法错误不记作执行。其他宿主或环境异常沿用上游处理，可能没有可分析的完整 observation。
- 轨迹和 post 分析保留原始 observation。面向模型的输出先截断或格式化，再附加提示。JSON 模式下，展示的 `observation` 超过宿主上限时也会截断；轨迹仍保留原始输出。
- 对成功解析的调用，普通消息和原生重试消息都会保留 function-call ID 与 thinking blocks。宿主 parser 在得到有效调用前拒绝的响应仍使用宿主的格式错误处理。`step.extra_info["toolpulse"]` 中的元数据可安全序列化为 JSON，包括执行状态、检测或渲染的事件与提示文本。post 事件元数据包含已交付提示所对应的事件；被 post renderer 丢弃的事件不会单独暴露。
- 新任务开始时，`setup()` 重置 ToolPulse、此前的宿主历史、轨迹和执行计数。该 adapter 不增加对独立 `RetryAgent` 工厂的支持。

adapter 不修改 SWE-agent 的通用原生重试策略；pre 拒绝预算与上游格式或工具重试上限相互独立。历史中的旧 observation 仍由宿主消息历史处理器管理。

## 测试

```bash
python -m pytest tests/integrations/sweagent tests/test_action_inspection.py
```

parser 与导入隔离测试无需 SWE-agent；未安装可选宿主时，宿主集成测试会跳过。若要在不安装源码包的情况下测试指定版本，可在已安装上游依赖的环境中，将源码路径加入 `PYTHONPATH`：

```bash
PYTHONPATH=/path/to/SWE-agent:/path/to/ToolPulse/src \
  python -m pytest tests/integrations/sweagent
```

# ToolPulse

[English](README.md) | [简体中文](README.zh-CN.md)

**面向任务型智能体、基于状态流追踪的在线工具使用辅助中间件。**

ToolPulse 为智能体的自主工具使用提供基础支持。它跨交互追踪执行上下文与工具使用的时序模式，在调用执行前检查拟议动作，在智能体继续行动前分析工具反馈。持续演化的状态帮助它结合智能体的工作节奏，识别笨拙的工具操作和工具使用中的绕路行为。

当需要介入时，ToolPulse 可以给出提醒、提供针对当前上下文的建议，或由宿主拦截依据不足的调用。它像举重时的保护者，在需要时给予提示或搭一把手，而推进任务的责任仍由智能体承担。

## 快速开始

需要 **Python 3.10+**。在仓库根目录执行：

```bash
python -m pip install -e .
python examples/minimal_react/run.py
```

这会运行一个完整的最小 ReAct 循环，包含两种在内存中执行的工具。安装依赖后，演示无需 API key、模型服务、网络访问、Docker 或 SWE-agent。

七个预设动作依次展示 Blind Command、Failure Inertia 和 Calling Repetition，以及修改后的成功检查。输出包含：

```text
Tool-use notice: You tried to edit note.txt using file before inspecting the file in the current task.
Tool-use notice: You received test_failure error again from check without taking an effective recovery action after the previous error.
Tool-use notice: You called check with exactly the same arguments in 3 consecutive steps.
...
Finished
```

决策使用预设顺序以便复现，不会根据提示改变；工具结果来自对内存文件的实际操作。完整说明见 [minimal ReAct 示例](examples/minimal_react/README.zh-CN.md)。

## 工作方式

ToolPulse 跨交互维护执行状态，在两个时点检查工具使用：

```text
智能体提出工具调用
  → 基于当前上下文执行 pre 检查
  → 宿主执行或拦截调用
  → 对已执行调用的反馈进行 post 分析
  → 将辅助信息加入智能体的下一轮输入
```

当前检测器覆盖五类行为：

| 行为 | 检测信号 |
|---|---|
| Blind Command | 在当前任务中尚未查看文件就尝试修改 |
| Calling Repetition | 连续使用相同动作和参数调用工具 |
| Failure Inertia | 缺少中间恢复信号的反复失败 |
| Functional Cycle | 语义动作序列反复出现 |
| Strategic Fixation | 连续交互窗口中的行为高度相似 |

框架提供动作语法与语义，ToolPulse 提供共享的状态追踪、检测和辅助信息生成能力。宿主控制工具执行，并将反馈交给智能体。

## 三种辅助形式

ToolPulse 围绕方法中的三种形式提供辅助：

| 形式 | 目的 | 当前实现机制 |
|---|---|---|
| **言语提示（verbal cueing）** | 用简短提醒指出行为，或引导下一步操作 | 模板提示：`remind_only` 和 `remind_and_guide` |
| **视觉提示（visual cueing）** | 通过结构化呈现，让文本反馈更容易区分 | `different_message_type`：返回分别包含 `observation` 和 `hint` 字段的 JSON 字符串 |
| **保护性辅助（tactile spotting）** | 借助快速辅助语言模型，提供针对当前上下文的建议 | `LLMHintProvider`，由调用方配置模型客户端 |

这里的视觉提示采用结构化文本；保护性辅助沿用举重保护者的比喻，指辅助模型提供的帮助。模型选择和响应速度取决于配置的服务。两个示例默认均使用模板提示，不额外调用辅助模型。

体验结构化反馈：

```bash
python examples/minimal_react/run.py --hint-set different_message_type
```

如需辅助模型生成建议，先通过 `python -m pip install -e '.[llm]'` 安装可选客户端依赖，再按[实现指南](docs/implementation-guide.md)配置 provider 和模型客户端。

## 示例

| 示例 | 展示内容 | 运行条件 |
|---|---|---|
| [minimal ReAct](examples/minimal_react/README.zh-CN.md) | 可直接修改的循环、独立动作解析器与语义标签，以及明确的 pre/post 接入点 | 仅需 ToolPulse；决策采用预设顺序 |
| [SWE-agent](examples/swe_agent/README.zh-CN.md) | 通过可复用 adapter 接入已有智能体的执行与消息生命周期 | Python 3.11+、文档指定的官方 SWE-agent 版本；执行任务需要 Docker |

SWE-agent 示例默认使用交互式 `human` 模式，无需 API key。使用模型自动执行时，需要配置模型服务及其要求的凭据。`--check-config` 可以在不启动 Docker、不调用模型的情况下验证配置。安装与启动命令见该示例的 README。

## 接入新框架

新框架需要提供**动作解析器**与**语义解析器（labeler）**，包括语义标签表、工具使用类型、错误指纹，以及文件读写等相关上下文。minimal ReAct 的这些组件位于 `src/toolpulse/parsing/minimal_react.py` 和 `src/toolpulse/semantics/minimal_react/`。

在宿主循环中，执行前调用 `inspect_action()`，对每次已执行动作调用一次 `observe_step()`。用 `assemble_observation()` 将返回的提示与工具反馈合并，交给智能体的下一轮输入；开始新任务时重置会话。宿主可以根据 pre 检查事件选择拦截调用或提醒后继续执行。

[minimal ReAct 示例](examples/minimal_react/README.zh-CN.md)完整展示了这些步骤。[实现指南](docs/implementation-guide.md)提供 parser、labeler、detector、provider 和 sink 的扩展说明。

## 仓库结构

```text
ToolPulse/
├── src/toolpulse/        # 可复用中间件与框架接入实现
│   ├── parsing/         # 框架动作解析器
│   ├── semantics/       # 语义标签表、语义解析与错误分类
│   ├── integrations/    # 已有智能体框架的适配器
│   └── ...              # 共享状态、检测器、提示与可选模型客户端
├── examples/
│   ├── minimal_react/   # 可直接修改的预设 ReAct 循环
│   └── swe_agent/       # 官方 SWE-agent 的配置与运行入口
├── tests/               # 单元、集成与兼容回归测试
├── docs/                # 实现指南与设计文档
└── pyproject.toml       # 包元信息与依赖
```

框架的解析器和语义定义放在 `src`，示例提供使用这些组件的宿主循环或运行入口。两个示例均提供中英文 README。

## 实现范围与开发

检测采用启发式，触发提示后仍需结合上下文判断。当前实现包含一个多粒度检测器、最小 ReAct 语义体系，以及面向 Python、Java、C++ 仓库任务的语义体系。SWE-agent adapter 支持文档指定版本的 `DefaultAgent`。两个示例用于展示接入流程，不构成任务效果评测。

安装开发依赖并运行测试：

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

未安装可选宿主时，需要 SWE-agent 的测试会跳过。[实现指南](docs/implementation-guide.md)保留了原 README 中的架构、API 契约、ToolFamiliar 代码映射和有意保留的兼容差异。

## 许可证

ToolPulse 采用 [MIT 许可证](LICENSE)。改编自上游的代码所涉及的版权声明与许可条款保留在[第三方声明](THIRD_PARTY_NOTICES.md)中。

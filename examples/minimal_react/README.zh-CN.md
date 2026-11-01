# ToolPulse + minimal ReAct

[English](README.md) | [简体中文](README.zh-CN.md)

这是与 SWE-agent 并列的第二种框架接入示例。框架本身只有一个直接展开的 ReAct 循环、两种 action 和一个预设决策函数，不需要模型、网络、Docker 或 SWE-agent。

动作解析器和语义定义属于 ToolPulse 的 `src`；本目录提供框架的工具实现、循环与演示任务。预设决策方便复现，工具结果由内存中的实际操作生成。

## 运行

在 ToolPulse 仓库根目录执行：

```bash
python -m pip install -e .
python examples/minimal_react/run.py
python examples/minimal_react/run.py --hint-set different_message_type
```

任务是把内存文件 `note.txt` 改成 `ready`，再检查。默认七次工具调用：

| 步骤 | Action | 结果与提示 |
|---|---|---|
| 1 | 写入 `broken` | pre 提示 Blind Command；本例提醒后仍执行 |
| 2 | 读取文件 | 得到 `broken`，建立已读记录 |
| 3 | 检查是否为 `ready` | 失败 |
| 4 | 再次检查 | 失败，post 提示 Failure Inertia |
| 5 | 第三次检查 | 失败，post 提示 Calling Repetition |
| 6 | 写入 `ready` | 成功；OPERATE 按现有启发式清理失败簇 |
| 7 | 检查是否为 `ready` | 成功；记录此步骤后结束 |

每轮输出 Thought、Action 和带提示的 Observation，最后输出 `Finished`。所有文件操作均在字典里，不修改磁盘文件。

## src 中的框架适配

| 文件 | 职责 |
|---|---|
| [`parsing/minimal_react.py`](../../src/toolpulse/parsing/minimal_react.py) | `MinimalReactParser`：框架 JSON action → `Action`，验证工具名与必要参数 |
| [`semantics/minimal_react/labeler.py`](../../src/toolpulse/semantics/minimal_react/labeler.py) | `KIND_OF_LABEL` 和 `MinimalReactLabeler`：语义标签、文件属性、错误分类、错误指纹及 post 编辑记录 |
| [`middleware.py`](../../src/toolpulse/middleware.py) | `ToolPulse.for_minimal_react()`：装配这个框架的 parser 和 labeler，复用其余组件 |

公开导入也支持显式装配：

```python
from toolpulse import MinimalReactLabeler, MinimalReactParser, ToolPulse

pulse = ToolPulse(
    parser=MinimalReactParser(),
    labeler=MinimalReactLabeler(),
)
# 等价的框架预设：pulse = ToolPulse.for_minimal_react()
```

Action 是包含 `tool` 和 `args` 的 JSON 字符串，两种工具的参数如下：

```json
{"tool": "file", "args": {"mode": "read", "path": "note.txt"}}
{"tool": "file", "args": {"mode": "write", "path": "note.txt", "content": "ready"}}
{"tool": "check", "args": {"path": "note.txt", "expected": "ready"}}
```

`file/write` 只修改已有文件，本例没有创建文件的动作。空白 action 可解析为空动作；其他非法 JSON、工具或参数会在 pre 阶段抛出 `ValueError`，尚未执行或记录。

Observation 同样使用 JSON 字符串，协议是 `{"ok": true, ...}` 或 `{"ok": false, "error": "非空错误说明"}`。读取成功时附带 `content`。labeler 在 post 读取该协议：`check` 失败映射为 `test_failure`，文件操作失败映射为 `runtime`；完整错误说明作为稳定指纹。这适用于本例固定格式的错误，真实框架应根据自己的错误协议归一化指纹。

| 语义标签 | Kind | 条件 |
|---|---|---|
| `read` | RETRIEVE | `file/read` |
| `write` | OPERATE | `file/write` |
| `check_ok` | COMPUTE | 检查未报告错误 |
| `check_failed` | COMPUTE | 检查失败 |
| `empty` | OTHER | 空白动作的兜底标签 |

三个主要 kind 分别只有 1、1、2 个标签。自定义标签可直接进入 grammar；核心显示函数会原样显示未知标签，无需修改全局标签表。pre 尚无执行结果，检查暂记为 `check_ok`，不会提交到轨迹。

`LabelInfo` 的属性使通用检测器能够工作：`target_file` 指定路径，`is_patch` 标记写入，`is_create=False` 表示本例无创建动作；成功读取才在 post 设置 `is_read`，由检测器记录文件知识。labeler 只在成功写入的 post 调用 `record_edit()`；pre 的 `record=False` 保持只读。错误类型和指纹通过 `LabelInfo.error` 交给失败检测。

## 循环里的接入点

[`run.py`](run.py) 的 `run()` 直接展示完整链路：

1. `reset()` 并设置任务描述，建立本任务的文件和消息历史。
2. 决策函数读取历史，返回 Thought 与 Action。
3. 构造 `StepObservation`，调用 `inspect_action()`；本例采用提醒后继续执行的策略。
4. 执行工具，把原始 JSON 结果和耗时填回步骤，再调用一次 `observe_step()`。
5. `assemble_observation(raw_result, pre_hints + post_hints)`，将结果加入历史，进入下一轮。
6. 决策函数返回 `None` 时结束；另有 20 步上限。已执行步骤不设置 `done=True`，保证最后一次检查也进入 post 分析。

默认提示用 `<tool_pulse>...</tool_pulse>` 包裹；`different_message_type` 使用含 `observation` 和 `hint` 字段的 JSON 字符串，仍是同一条消息内容。默认 sink 已收集 hints，不需要额外投递层。

`scripted_model(history)` 用历史中的动作数选取预设步骤。它不会因提示改变动作；如需真实 agent，在这个函数中调用模型，让模型读取同一份 history 并生成符合协议的动作即可。本例使用普通 assistant/user 文本消息，因此没有 provider 工具调用 ID 的配对逻辑。

## 接入新框架时需要替换什么

| 接入职责 | minimal ReAct | SWE-agent |
|---|---|---|
| 解析动作 | `MinimalReactParser`，简单 JSON | `SweAgentParser` 加原生工具调用 parser |
| 定义语义 | 自己的标签表和 `MinimalReactLabeler` | repo 标签表和 `RepoLabeler` |
| 识别错误、提供文件语义 | 明确的 JSON 结果、路径与读写标记 | repo 错误解析、工具参数与宿主上下文 |
| 装配组件 | `for_minimal_react()` | `for_swe_repo()`，adapter 安装原生调用 parser |
| pre / 执行 / post | 在本例循环中直接调用 | `ToolPulseSWEAgent` 覆盖方法并注册执行 hook |
| 将提示放回下一轮 | 合并 observation 后追加历史 | 适配工具响应、宿主模板、截断和重试消息 |
| 新任务与终止 | `run()` 重置；预设序列结束或步数上限 | adapter 的 setup、宿主结束逻辑及拒绝预算 |

检测器、会话状态、提示 provider/sink 和 observation assembly 都可复用。只有需要新增检测规则或提示内容时才扩展它们。SWE-agent 需要额外 adapter 来进入已有生命周期；本例的循环可直接修改，因此无须再封装 agent 类。

## 验证

```bash
python -m pytest -q tests/parsing/test_minimal_react.py \
  tests/semantics/test_minimal_react_labeler.py tests/test_minimal_react_example.py
```

覆盖参数验证、pre 只读、文件读写语义、失败聚类，以及普通和 JSON 提示格式的完整演示流程。

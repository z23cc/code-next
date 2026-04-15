# Python 实现规范（给 Claude Code 的执行蓝图）

## 1. 目标

实现一个名为 `aiwf` 的 Python 工作流内核，作用是把任务输入、runbook 语义、上下文发现、宿主执行、gates、artifacts 和 resume 串成一个稳定流程。

这个内核应当可以作为后续 RepoPrompt Agent Run、Claude Code、Codex 的共享底座，但第一阶段只要求把 **Claude Code 路径走通**。

## 2. 设计立场

### 2.1 真源优先
所有流程语义应来自 `.ai/`，而不是硬编码在 Python 里。  
当前阶段中，Python 代码仍拥有主要的 `plan / implement / review / resume` 控制流；runbook 更偏向可校验的工作流契约说明与阶段边界描述，而不是单独驱动全部分支与状态迁移。

### 2.2 文件协议优先
第一阶段不依赖数据库。  
所有状态和产物都应该是可读、可审计、可恢复的文件。

### 2.3 Claude 适配应当很薄
不要在 Python 核心里写大量 Claude Code 专属逻辑。  
Claude 适配器的职责只是：
- 组合 prompt / context
- 调用 Claude Code CLI 或与其技能工作流协作
- 解析执行结果
- 把结果写回统一 artifact 协议

## 3. 推荐依赖

```toml
typer = "^0.12"
pydantic = "^2.8"
PyYAML = "^6.0"
rich = "^13.7"
pytest = "^8.0"
ruff = "^0.6"
mypy = "^1.10"
```

如非必要，不要在第一阶段引入：
- celery
- sqlalchemy
- fastapi
- redis
- networkx
- 复杂插件框架

## 4. 包结构建议

```text
src/aiwf/
  __init__.py
  cli.py
  models.py
  loader.py
  engine.py
  artifacts.py
  gates.py
  state.py
  exceptions.py
  adapters/
    __init__.py
    base.py
    claude_code.py
    rp_agent.py
  compilers/
    __init__.py
    claude.py
tests/
```

### 4.1 `models.py`
定义：
- `TaskSpec`
- `RunbookSpec`
- `StageSpec`
- `GateSet`
- `GateCommand`
- `WorkReceipt`

### 4.2 `loader.py`
负责从 `.ai/` 读取：
- task
- runbook
- gate set
- policy

### 4.3 `state.py`
负责：
- 生成 `run_id`
- 初始化 run 目录
- 管理 `run.json`
- append `events.ndjson`

### 4.4 `artifacts.py`
负责标准产物的路径与落盘逻辑：
- `context-pack.md`
- `exec-plan.md`
- `verify-report.json`
- `review-report.json`
- `work-receipt.json`

### 4.5 `gates.py`
负责：
- 加载 gate set
- 顺序执行命令
- 捕获 stdout/stderr
- 生成 `verify-report.json`

### 4.6 `engine.py`
这是第一阶段的核心编排器。  
它应提供：

- `run_plan(task_path)`
- `run_implement(task_path)`
- `run_review(run_id)`
- `resume(run_id)`

### 4.7 `adapters/base.py`
定义统一适配器协议，例如：

- `discover()`
- `plan()`
- `execute()`
- `review()`

### 4.8 `adapters/claude_code.py`
实现 Claude Code 的薄适配。  
第一阶段可接受的方式：

- 通过 subprocess 调用 `claude`
- 把 prompt / 输入文件路径交给 Claude Code
- 将标准输出解析为 artifact 内容或结果摘要

如果任务环境不适合直接自动执行，也可以先把该适配器实现为“生成交互 prompt 并在 run 边界停下等待人工继续”的半自动版本。

## 5. CLI 设计

建议使用 `typer`，命令面如下：

```bash
uv run aiwf run plan --task .ai/tasks/example.md
uv run aiwf run implement --task .ai/tasks/example.md
uv run aiwf run review --run-id <run_id>
uv run aiwf resume <run_id>
uv run aiwf compile claude
```

### 5.1 CLI 输出原则
- 给用户明确状态
- 不隐藏关键失败信息
- 所有 run 都打印 `run_id`
- 失败时指出 artifact 或日志位置

### 5.2 `compile claude` 最小投影契约

`compile claude` 不应只做简单 bundle 导出；最小可行版本至少应输出：

- 一个 Claude 可直接消费的 markdown bundle
- 一个显式宿主投影文件（命令、artifact、workflow 边界）
- 一个带 source fingerprint 与 drift 信息的 manifest

## 6. 运行目录契约

每次运行都创建：

```text
.ai/runs/<run_id>/
  run.json
  events.ndjson
  task.md
  context-pack.md
  exec-plan.md
  verify-report.json
  review-report.json
  work-receipt.json
  logs/
```

其中：
- `run.json` 是当前快照
- `events.ndjson` 是 append-only 事件流
- `work-receipt.json` 是最终摘要

## 7. 最小可行流程

### `plan`
1. 读取 task
2. 初始化 run
3. 调用 adapter 做 discover
4. 调用 adapter 做 plan
5. 写入 `context-pack.md`
6. 写入 `exec-plan.md`
7. 写入 `work-receipt.json`

### `implement`
1. 读取 task
2. 初始化 run
3. discover
4. plan（可复用已有 plan）
5. execute
6. 如果是手动 Claude 模式，可在实现 handoff prompt 处先停为 `blocked`
7. run gates
8. gates 通过后进入 `needs_review`
9. 由显式 review 步骤继续，而不是自动把 prompt 生成视为 review 完成

### `review`
1. 读取既有 run 与 artifacts（不是重新从 task 启动一条独立 review run）
2. 收集 verify-report / diff / review 上下文
3. 做独立 review
4. 输出 `review-report.json`
5. 手动 Claude 模式下可再次停在 `blocked`，由后续 `resume(run_id)` 完成终态收口

## 8. 第一阶段的现实取舍

优先完成这些：
- schema 稳定
- 状态可恢复
- artifact 可落盘
- Claude Code 路径可跑通

可以暂缓这些：
- 多宿主切换
- 并发 stage
- 复杂权限模型
- 插件市场分发

## 9. 给 Claude Code 的实现顺序

最推荐的提交顺序：

### 第 1 提交
- `models.py`
- `loader.py`
- `state.py`

### 第 2 提交
- `artifacts.py`
- `gates.py`

### 第 3 提交
- `engine.py`
- `cli.py`

### 第 4 提交
- `adapters/base.py`
- `adapters/claude_code.py`

### 第 5 提交
- `compile claude` 路径
- 测试与文档补齐

## 10. 质量门槛

必须满足：

- task / runbook / gate 可以独立加载
- `run.json` 始终可读
- gate 失败时状态正确落盘
- 终态 run 会生成 `work-receipt.json`，非终态 handoff run 不应伪造 receipt
- 异常信息包含路径与阶段
- 测试覆盖至少包含 happy path 与一个 failure path

## 11. 不要这样做

- 不要把 YAML 字段随手解析成裸 dict 到处传
- 不要把状态更新散落在多个函数里而没有统一入口
- 不要把 Claude Code prompt 拼接逻辑埋进 `engine.py`
- 不要为了“通用性”过早抽象多层插件体系
- 不要在第一阶段引入数据库

## 12. 交付标准

第一版交付应能完成这个 demo：

1. 读取 `.ai/tasks/TEMPLATE.md` 改造出的真实任务
2. `uv run aiwf run plan --task ...` 成功创建 run 目录
3. `context-pack.md` 与 `exec-plan.md` 被写出
4. `uv run aiwf run implement --task ...` 能正确经历 handoff / gates / needs_review 边界
5. `uv run aiwf run review --run-id ...` 与 `uv run aiwf resume <run_id>` 能把 review 终态正确收口，并写出 `work-receipt.json`

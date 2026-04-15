# 项目目标

本仓库的目标是实现一个 **Python 版 `aiwf` 工作流内核**，用于驱动 RepoPrompt / Claude Code / Codex 之间的统一 runbook 流程。  
`aiwf` 的核心职责是：读取 task、读取 runbook、发现上下文、调用执行宿主、运行 gates、落盘 artifacts、支持 resume。

## 当前范围

第一阶段只实现以下能力：

1. `plan`
2. `implement`
3. `review`
4. `resume`
5. artifact store
6. gate runner
7. host compiler（先只生成 Claude Code 需要的文件）

## 非目标

当前阶段不要做这些事情：

- 不实现 Web UI
- 不实现数据库持久化
- 不实现云端队列
- 不实现复杂多 agent supervisor
- 不把聊天记录作为 authoritative state
- 不把宿主配置写死在 Python 代码中

## 真源与目录规则

本项目的真源在 `.ai/`，而不是 `.claude/`。

- `.ai/policies/`：项目策略、评审规则
- `.ai/runbooks/`：工作流契约说明与阶段边界
- `.ai/gates/`：确定性校验命令
- `.ai/tasks/`：任务输入
- `.ai/runs/`：每次运行的状态与产物

`.claude/` 只承载 Claude Code 的执行入口，例如 skills。

## Python 技术约束

默认采用：

- Python 3.11+
- `typer`：CLI
- `pydantic`：配置与 schema
- `PyYAML`：YAML 读写
- `rich`：CLI 输出
- 标准库 `subprocess` / `pathlib` / `json` / `dataclasses`（如需要）

除非任务明确要求，否则不要引入重量级运行时依赖。

## 建议包结构

```text
src/aiwf/
  cli.py
  models.py
  loader.py
  engine.py
  artifacts.py
  gates.py
  state.py
  adapters/
    rp_agent.py
    claude_code.py
  compilers/
    claude.py
```

## 核心对象

至少实现这些对象：

- `TaskSpec`
- `RunbookSpec`
- `GateSet`
- `RunState`
- `ArtifactStore`
- `StageResult`
- `RunnerAdapter`
- `ClaudeCodeAdapter`

对象定义应优先服务于文件协议与可恢复执行，而不是服务于某个单一宿主。

## 运行状态

运行状态采用有限状态机：

`queued -> running -> blocked -> needs_review -> passed | failed | canceled`

每个 run 必须写入：

- `.ai/runs/<run_id>/run.json`
- `.ai/runs/<run_id>/events.ndjson`

## 强制产物

以下产物在第一阶段必须支持：

- `context-pack.md`
- `exec-plan.md`
- `verify-report.json`
- `work-receipt.json`

## Claude Code 的工作方式

每次处理任务时，遵循以下顺序：

1. 先读 `CLAUDE.md`
2. 再读任务文件与相关 runbook
3. 优先最小改动，不做无关重构
4. 先产出计划，再做实现
5. 对手动 Claude 模式，要把 prompt 文件视为人工 handoff 边界，而不是视为实现或 review 已经终态完成
6. 实现完成后必须跑 gates
7. review 现在基于既有 run 与 artifacts，通过 `run review --run-id <run_id>` 进入
8. 所有关键决定写入 artifact
9. 如果上下文过大，拆分任务，不要把过多设计塞进一次回答

## 编辑原则

- 不擅自重命名目录或大规模搬迁文件
- 不引入未经要求的新框架
- 不修改与当前任务无关的代码
- 优先修正根因，不做表面补丁
- 优先补最小必要测试
- 优先写清晰代码，而不是技巧性代码

## Definition of Done

一个任务只有在满足下面条件后才算完成：

1. 目标文件已经修改完毕
2. gates 运行完成，结果已记录
3. 必要 artifact 已落盘
4. run 已到达终态；如果仍处于 `blocked` 或 `needs_review`，说明只是到达 handoff 边界，不算完成
5. 变更范围与任务范围一致
6. 关键风险与剩余问题已在 `work-receipt.json` 中说明

## 技能使用建议

当任务需要多步操作时，优先使用这些 skills：

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

如果一个流程已经可以写成 skill，就不要继续把长操作步骤塞进 `CLAUDE.md`。

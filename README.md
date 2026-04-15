# aiwf Phase 1

`aiwf` 是一个面向 Claude Code / RepoPrompt / Codex 工作流的 Python 内核。  
Phase 1 现已实现：

- `aiwf run plan`
- `aiwf run implement`
- `aiwf run review`
- `aiwf resume`
- `aiwf compile claude`
- 文件化 run 状态与 artifacts
- 确定性 gates
- Claude 手动优先适配器与 stub 适配器

## 目录概览

- `src/aiwf/`：工作流内核
- `.ai/`：runbook、task、policy、gate、run 产物真源
- `.claude/skills/`：Claude Code 技能入口
- `docs/PYTHON_IMPLEMENTATION_SPEC.md`：实现规范
- `docs/QUICKSTART.md`：快速上手

## 安装

```bash
uv sync --extra dev
```

## uv 开发说明

- 使用 `uv sync --extra dev` 初始化并同步开发依赖。
- 使用 `uv run <cmd>` 在项目环境中运行命令（无需手动激活虚拟环境）。
- 快速验证可运行：`uv run pytest tests/ -x -q`。

## 常用命令

```bash
uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude
uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude
uv run aiwf run review --run-id <run_id>
uv run aiwf resume <run_id>
uv run aiwf inspect <run_id>
uv run aiwf compile claude --output .claude/compiled
```

说明：

- `--adapter claude` 为默认值，走 Claude Code 手动优先模式。
- `--adapter stub` 适合测试和本地调试。
- `--auto` 会在所选 adapter 的显式宿主契约支持时启用自动模式；当前 Claude 支持，RP / stub 不支持。
- `run review` 现在面向已有 run：先让 implement run 到达 `needs_review`，再用 `--run-id` 启动 review。
- `resume` / `run review` 会恢复 run 中已存储的 `host_contract`，而不是要求再次手动指定 adapter 语义。
- `inspect` 会读取 `run-diagnostics.json` 与 `run-provenance.json`，直接告诉你 run 为什么停下、下一步做什么、关键证据 artifacts 在哪里。
- `compile claude` 会生成 Claude 宿主投影文件与 drift-aware manifest，而不只是简单 bundle 导出。

## 宿主契约与 review 证据契约

运行时现在不再只依赖 `adapter + auto` 的薄组合语义，而是会把显式 `host_contract` 落盘到 `run.json.data` 中。该契约至少包含：

- adapter 名称与 mode（manual / auto）
- auto support / manual review handoff 等 capability
- review/runtime 所需的 evidence contract：
  - review 前必须存在哪些 artifacts
  - `review-report.json` 至少必须包含哪些字段
  - review 报告中引用的证据 artifact（如 `prompt_file` / `response_file`）是否必须存在

当前内置适配器的最小 review 契约：

- Claude manual：要求 `verify-report.json`，review report 需包含 `summary` / `issues` / `mode` / `prompt_file`
- Claude auto：要求 `verify-report.json`，review report 需包含 `summary` / `issues` / `mode` / `response_file`
- RP manual：要求 `verify-report.json`，review report 需包含 `summary` / `issues` / `mode` / `prompt_file`
- stub：要求 `verify-report.json`，review report 需包含 `summary` / `issues`

## 产物契约

每次运行都会创建 run 目录与状态文件；其余 artifacts 会按当前阶段逐步出现：

```text
.ai/runs/<run_id>/
  run.json
  events.ndjson
  context-pack.md
  exec-plan.md
  claude-implement-prompt.md      # manual Claude implement handoff only
  verify-report.json              # after gates run
  claude-review-prompt.md         # manual Claude review handoff only
  review-report.json              # after review step runs
  work-receipt.json               # terminal summary only
  run-diagnostics.json            # status/reason/next-actions surface
  run-provenance.json             # artifact index + gate/review evidence navigation
```

当 run 处于 `blocked` / `needs_review` / `failed` 时，CLI 会直接打印：

- `reason=...`
- 一到两个 `next=...`
- `diagnostics=...`
- `provenance=...`
- `inspect=uv run aiwf inspect <run_id> --ai-root ...`

如果需要完整查看 explainability surface，可运行：

```bash
uv run aiwf inspect <run_id>
```

该命令会汇总：

- 当前 workflow / status / last completed stage
- 停止原因与 next actions
- 宿主契约关键能力（mode / auto support / review handoff）
- gate evidence
- review evidence 与 linked artifacts
- run-level artifact index

## 默认 gates

默认 gate 集位于 `.ai/gates/default.yaml`，包含：

- `uv run ruff check src/ tests/`
- `uv run mypy src/aiwf/`
- `uv run pytest tests/ -x -q`

## Claude Code 技能

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

这些技能最终调用 `aiwf` CLI，并把关键结果落盘到 `.ai/runs/`。

## Claude 编译投影契约

`uv run aiwf compile claude --output .claude/compiled` 现在会生成：

- `.claude/compiled/claude-bundle.md`：Claude 可读的合并说明与 traceability index
- `.claude/compiled/claude-projection.json`：显式宿主投影契约（host contract / review artifact contract / workflow 边界）
- `.claude/compiled/manifest.json`：带 source fingerprint / output hash / drift 状态的编译清单

当前 Claude 编译器已切到共享 compiler/projection helpers，并直接复用现有 adapter host contract 作为 projection variant 真源，因此在不改变 CLI 与输出文件名的前提下，为后续宿主扩展保留了统一抽象层。

重复编译同一输出目录时，`manifest.json` 会基于上一版 manifest 标记 `initial` / `clean` / `changed`，帮助发现 `.ai` 真源与 Claude 投影之间的漂移。

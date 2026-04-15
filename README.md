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
uv run aiwf compile claude --output .claude/compiled
```

说明：

- `--adapter claude` 为默认值，走 Claude Code 手动优先模式。
- `--adapter stub` 适合测试和本地调试。
- `--auto` 会尝试调用本机 `claude` CLI。
- `run review` 现在面向已有 run：先让 implement run 到达 `needs_review`，再用 `--run-id` 启动 review。
- `resume` 会恢复 run 中已存储的 `adapter` / `auto` 设置，而不是要求再次手动指定。
- `compile claude` 会生成 Claude 宿主投影文件与 drift-aware manifest，而不只是简单 bundle 导出。

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
```

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
- `.claude/compiled/claude-projection.json`：显式宿主投影契约（命令、artifact、workflow 边界）
- `.claude/compiled/manifest.json`：带 source fingerprint / output hash / drift 状态的编译清单

重复编译同一输出目录时，`manifest.json` 会基于上一版 manifest 标记 `initial` / `clean` / `changed`，帮助发现 `.ai` 真源与 Claude 投影之间的漂移。

# Quickstart

## 1. 安装

```bash
uv sync --extra dev
```

> 开发与运行统一使用 `uv run <cmd>`（无需手动激活虚拟环境）。

## 2. 创建任务

复制 `.ai/tasks/TEMPLATE.md`，按你的任务改名并填写内容。

## 3. 规划阶段

```bash
uv run aiwf run plan --task .ai/tasks/<your-task>.md --adapter claude
```

可选 adapter：`claude` / `rp` / `codex` / `stub`。

计划 artifacts：

- `.ai/runs/<run_id>/context-pack.md`
- `.ai/runs/<run_id>/exec-plan.md`

同时 run metadata 会保存显式 `host_contract`，供后续 `run review` / `resume` 恢复宿主能力边界。

## 4. 实现阶段

```bash
uv run aiwf run implement --task .ai/tasks/<your-task>.md --adapter claude
```

manual-first 宿主在该阶段可能停在 `blocked`，然后通过 prompt handoff + `resume` 推进：

```bash
uv run aiwf resume <run_id>
```

如果 gates 通过，run 会停在 `needs_review`；如果 gates 失败，修复后同样使用 `resume` 继续。

`--auto` 仅在宿主契约声明支持自动执行时生效；当前仅 `claude` 支持。

## 5. 复核阶段

对已经到达 `needs_review` 的 run 执行：

```bash
uv run aiwf run review --run-id <run_id>
```

manual-first review 也可能先停在 `blocked`，完成手动复核后继续：

```bash
uv run aiwf resume <run_id>
```

review 阶段会按 `host_contract.review` 校验：

- review 前必需 artifacts（如 `verify-report.json`）
- `review-report.json` 必需字段
- 报告中引用的 linked evidence artifact 是否存在

## 6. 查看 run 为什么停下

```bash
uv run aiwf inspect <run_id>
```

该命令会汇总：

- 当前状态、停止原因、next actions
- 宿主契约关键能力
- gate/review evidence
- artifact index（`--verbose` 可展开）

核心 explainability artifacts：

- `.ai/runs/<run_id>/run-diagnostics.json`
- `.ai/runs/<run_id>/run-provenance.json`

## 7. 契约与环境检查

```bash
uv run aiwf contracts lint
uv run aiwf doctor --json
```

## 8. 编译宿主投影

```bash
uv run aiwf compile claude --output .claude/compiled
uv run aiwf compile codex --output .codex/compiled
```

生成内容包括 bundle / projection / manifest；manifest 记录 source fingerprint 与 drift 状态。

兼容性边界（`host_contract`、projection、install surface、legacy run metadata retention）见 `docs/compatibility-policy.md`。

## 9. Claude Code 技能入口

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

## 10. 默认验证

默认 gate 集会运行：

- `uv run ruff check src/ tests/`
- `uv run mypy src/aiwf/`
- `uv run pytest tests/ -x -q`

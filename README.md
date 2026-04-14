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
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

## 常用命令

```bash
aiwf run plan --task .ai/tasks/<task>.md --adapter claude
aiwf run implement --task .ai/tasks/<task>.md --adapter claude
aiwf run review --task .ai/tasks/<task>.md --adapter claude
aiwf resume <run_id>
aiwf compile claude --output .claude/compiled
```

说明：

- `--adapter claude` 为默认值，走 Claude Code 手动优先模式。
- `--adapter stub` 适合测试和本地调试。
- `--auto` 会尝试调用本机 `claude` CLI。

## 产物契约

每次运行会创建：

```text
.ai/runs/<run_id>/
  run.json
  events.ndjson
  context-pack.md
  exec-plan.md
  verify-report.json
  review-report.json
  work-receipt.json
```

## 默认 gates

默认 gate 集位于 `.ai/gates/default.yaml`，包含：

- `ruff check src/ tests/`
- `mypy src/aiwf/`
- `pytest tests/ -x -q`

## Claude Code 技能

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

这些技能最终调用 `aiwf` CLI，并把关键结果落盘到 `.ai/runs/`。

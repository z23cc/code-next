# Quickstart

## 1. 安装

```bash
uv sync --extra dev
```

> 开发与运行统一使用 `uv run <cmd>`（无需手动激活虚拟环境）。

## 2. 创建任务

复制 `.ai/tasks/TEMPLATE.md`，按你的任务改名并填写内容。

## 3. 规划阶段

使用默认 Claude 适配器：

```bash
uv run aiwf run plan --task .ai/tasks/<your-task>.md --adapter claude
```

计划 artifact 会写到：

- `.ai/runs/<run_id>/context-pack.md`
- `.ai/runs/<run_id>/exec-plan.md`

## 4. 实现阶段

```bash
uv run aiwf run implement --task .ai/tasks/<your-task>.md --adapter claude
```

如果 gates 失败，修复后可继续：

```bash
uv run aiwf resume <run_id>
```

## 5. 复核阶段

```bash
uv run aiwf run review --task .ai/tasks/<your-task>.md --adapter claude
```

## 6. 编译 Claude 输入包

```bash
uv run aiwf compile claude --output .claude/compiled
```

生成内容包括：

- `.claude/compiled/claude-bundle.md`
- `.claude/compiled/manifest.json`

## 7. Claude Code 技能入口

如果你更喜欢在 Claude Code 中触发，可使用：

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

## 8. 默认验证

默认 gate 集会运行：

- `uv run ruff check src/ tests/`
- `uv run mypy src/aiwf/`
- `uv run pytest tests/ -x -q`

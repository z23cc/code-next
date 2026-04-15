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

在默认手动 Claude 模式下，这一步通常会先停在 `blocked`：

- 查看 `.ai/runs/<run_id>/claude-implement-prompt.md`
- 完成实现工作后继续执行：

```bash
uv run aiwf resume <run_id>
```

如果 gates 通过，run 会停在 `needs_review`，等待显式 review。
如果 gates 失败，修复后同样使用 `uv run aiwf resume <run_id>` 继续。

## 5. 复核阶段

对已经到达 `needs_review` 的 run 执行：

```bash
uv run aiwf run review --run-id <run_id>
```

在手动 Claude 模式下，review 也可能先停在 `blocked`，此时查看 `.ai/runs/<run_id>/claude-review-prompt.md`，完成复核后再执行：

```bash
uv run aiwf resume <run_id>
```

## 6. 编译 Claude 输入包

```bash
uv run aiwf compile claude --output .claude/compiled
```

生成内容包括：

- `.claude/compiled/claude-bundle.md`
- `.claude/compiled/claude-projection.json`
- `.claude/compiled/manifest.json`

其中：

- `claude-bundle.md` 是 Claude 可直接阅读的合并包
- `claude-projection.json` 是 Claude 宿主投影契约
- `manifest.json` 会记录 source fingerprint 与上一次编译相比的 drift 状态

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

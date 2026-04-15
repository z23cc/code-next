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

同时 run metadata 会保存显式 `host_contract`，供后续 `run review` / `resume` 恢复宿主能力边界。

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

如果使用 `--auto`，只有当前宿主契约声明支持自动模式时才会生效；Claude 支持，RP / stub 不支持。

## 5. 复核阶段

对已经到达 `needs_review` 的 run 执行：

```bash
uv run aiwf run review --run-id <run_id>
```

在手动 Claude 模式下，review 也可能先停在 `blocked`，此时查看 `.ai/runs/<run_id>/claude-review-prompt.md`，完成复核后再执行：

```bash
uv run aiwf resume <run_id>
```

review 阶段会按当前 `host_contract.review` 契约检查：

- review 前是否已有 `verify-report.json`
- `review-report.json` 是否包含最小必需字段
- 报告中引用的证据 artifact（如 `prompt_file` / `response_file`）是否真实存在

## 6. 查看 run 为什么停下

当 run 停在 `blocked` / `needs_review` / `failed` 时，CLI 会直接打印：

- `reason=...`
- `next=...`
- `diagnostics=...`
- `provenance=...`
- `inspect=uv run aiwf inspect <run_id> --ai-root ...`

如果需要完整查看 explainability / evidence surface，执行：

```bash
uv run aiwf inspect <run_id>
```

该命令会汇总：

- 当前状态、最后完成阶段、停止原因
- 下一步建议操作
- 宿主契约关键能力
- `verify-report.json` 对应的 gate evidence
- `review-report.json` 与 linked review evidence
- run-level artifact index

对应运行目录中的核心 explainability artifacts 为：

- `.ai/runs/<run_id>/run-diagnostics.json`
- `.ai/runs/<run_id>/run-provenance.json`

## 7. 编译 Claude 输入包

```bash
uv run aiwf compile claude --output .claude/compiled
```

生成内容包括：

- `.claude/compiled/claude-bundle.md`
- `.claude/compiled/claude-projection.json`
- `.claude/compiled/manifest.json`

其中：

- `claude-bundle.md` 是 Claude 可直接阅读的合并包
- `claude-projection.json` 是 Claude 宿主投影契约，包含显式 host/review contract 元数据
- `manifest.json` 会记录 source fingerprint 与上一次编译相比的 drift 状态
- 当前 Claude compiler 已迁移到共享 projection helpers，并直接从既有 host contract 派生 variant 元数据，因此当前输出保持兼容，同时后续可以在同一抽象层上扩宿主

## 8. Claude Code 技能入口

如果你更喜欢在 Claude Code 中触发，可使用：

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

## 9. 默认验证

默认 gate 集会运行：

- `uv run ruff check src/ tests/`
- `uv run mypy src/aiwf/`
- `uv run pytest tests/ -x -q`

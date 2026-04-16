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

`--auto` 仅在宿主契约声明支持自动执行时生效；当前 `claude` 可稳定使用 auto。`rp` 保留实验性 `--auto` 路径，但只应在已验证实现 `aiwf-rp-native/v1` 的真实 RepoPrompt app / MCP CLI runtime 上尝试；默认请使用 manual handoff + `resume`。

`rp` 的 manual 模式还支持实验性的 `--bridge` 选项，当前有两种 bridge mode：

- `--bridge-mode manual-assist`：保留 operator 主导流程。`aiwf` 负责写 prompt / bridge metadata、尝试 context seeding，并可通过 `aiwf rp bridge capture ...` 把 RepoPrompt 侧输出拉回 aiwf artifacts。
- `--bridge-mode managed-agent`：`aiwf` 会通过 RepoPrompt agent/session surface 驱动 implement / review，并把 session log 写入 `rp-bridge-agent-log.json`。如果 agent 进入 `waiting_for_input`，run 会 deterministic 地停在 `blocked`，operator 处理完 RepoPrompt 侧输入后再执行 `resume`。

选择建议：

- 需要最稳的 fallback、愿意手工控制 RepoPrompt 节奏：选 `manual-assist`
- 希望由 `aiwf` 自动驱动 RepoPrompt agent lifecycle，并接受实验性 bridge 自动化：选 `managed-agent`

如果 implement 阶段是 `rp/manual + --bridge-mode manual-assist`，完成 RepoPrompt 侧实现后，可先 capture 再继续：

```bash
uv run aiwf rp bridge capture <run_id> --stage implement --source <rp-side-source>
uv run aiwf resume <run_id>
```

其中 `--source` 是 RepoPrompt 侧可被 bridge `read_file` 读取的路径或标识。capture 成功后会写入：

- `.ai/runs/<run_id>/rp-agent-implement-response.md`
- `.ai/runs/<run_id>/rp-bridge-capture.json`

如果 implement 阶段使用的是 `rp/manual + --bridge-mode managed-agent`，则不需要手工 capture；`aiwf` 会直接写出 `rp-agent-implement-response.md` 与 `rp-bridge-agent-log.json`。若 session 进入 `waiting_for_input`，先在 RepoPrompt 侧处理输入，再执行：

```bash
uv run aiwf resume <run_id>
```

## 5. 复核阶段

对已经到达 `needs_review` 的 run 执行：

```bash
uv run aiwf run review --run-id <run_id>
```

manual-first review 也可能先停在 `blocked`。如果是 `rp/manual + --bridge`，建议先 capture RepoPrompt 侧 review 输出：

```bash
uv run aiwf rp bridge capture <run_id> --stage review --source <rp-side-source>
uv run aiwf resume <run_id>
```

capture 成功后会把 RepoPrompt 侧响应写入 `rp-agent-review-response.md`，并把 `review-report.json` 规范化到当前 run 的 review contract；如果必需字段缺失，capture 会 deterministic 地拒绝、保留 run 在 `blocked`，同时把 refusal 写入 `rp-bridge-capture.json` 供 `inspect` / provenance 查看。

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
uv run aiwf compile rp --output .rp/compiled
uv run aiwf compile claude --output .claude/compiled
uv run aiwf compile codex --output .codex/compiled
```

生成内容包括 bundle / projection / install surface / manifest；manifest 记录 source fingerprint 与 drift 状态。

- 样例安装/集成方式见 `docs/INSTALL_GUIDE.md`
- 兼容性边界（`host_contract`、projection、install surface、legacy run metadata retention）见 `docs/compatibility-policy.md`

## 9. Claude Code 技能入口

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

## 10. 默认验证

默认 gate 集会运行：

- `uv run ruff check src/ tests/`
- `uv run mypy src/aiwf/`
- `uv run pytest tests/ -x -q`

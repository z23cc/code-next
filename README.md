# aiwf

`aiwf` 是一个面向 Claude Code / RepoPrompt / Codex 工作流的 Python 内核，提供统一的任务执行、状态落盘、契约校验与宿主投影编译。

当前实现重点：

- `run plan / implement / review / resume`
- 文件化 run 状态与 artifacts（含 diagnostics / provenance）
- 显式 `host_contract` 与 review evidence contract
- `inspect` explainability surface
- `contracts lint` 契约检查
- `doctor` 工作区自检
- `compile rp` / `compile claude` / `compile codex` 宿主投影与 drift manifest

## 目录概览

- `src/aiwf/`：工作流内核
- `.ai/`：runbook、task、policy、gate、run 产物真源
- `.claude/skills/`：Claude Code 技能入口
- `docs/PYTHON_IMPLEMENTATION_SPEC.md`：实现规范
- `docs/QUICKSTART.md`：快速上手
- `docs/INSTALL_GUIDE.md`：RP / Claude 编译产物的安装与集成方式
- `docs/compatibility-policy.md`：run metadata / host contract / projection 兼容性策略
- `docs/RP_PROVIDER_GAP_ANALYSIS.md`：真实 RepoPrompt CLI 与 aiwf provider 期待之间的差距分析
- `docs/RP_BRIDGE_DESIGN.md`：基于真实 `rp-cli` tool surface 的 bridge 集成方案
- `docs/RP_REAL_RUNTIME_VALIDATION.md`：真实 RepoPrompt runtime 的 scope 标签、doctor 启发式与操作员验证流程

## 安装

```bash
uv sync --extra dev
```

## uv 开发说明

- 使用 `uv sync --extra dev` 初始化并同步开发依赖。
- 使用 `uv run <cmd>` 在项目环境中运行命令（无需手动激活虚拟环境）。
- 快速验证：`uv run pytest tests/ -x -q`。

## 常用命令

```bash
uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude
uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude
uv run aiwf run review --run-id <run_id>
uv run aiwf resume <run_id>
uv run aiwf inspect <run_id>
uv run aiwf contracts lint
uv run aiwf doctor --json
uv run aiwf conformance rp --rp-command /usr/local/bin/rp-cli --json
uv run aiwf compile rp --output .rp/compiled
uv run aiwf compile claude --output .claude/compiled
uv run aiwf compile codex --output .codex/compiled
```

说明：

- 支持适配器：`claude` / `rp` / `codex` / `stub`（其中 `stub` 仅用于仓库内测试）。
- `--auto` 仅在宿主契约声明支持自动执行时生效；当前 `claude` 是稳定 auto 路径，`rp` 仅保留实验性 auto/native 路径，`codex` 仍是 manual-only。
- `rp` 当前稳定路径是 manual handoff + `resume`。产品层面唯一官方 RP target 是真实 RepoPrompt app / MCP CLI runtime；仓库内的 `rp-cli-stub` 仅用于协议/CI 测试，不代表真实 RepoPrompt runtime readiness。
- `codex` 当前仍是 manual-first（通过 handoff prompt + `resume` 流程推进）。
- `run review` 基于已有 run（`--run-id`），并按已存储的 `host_contract.review` 契约校验证据。

## 关键运行产物

```text
.ai/runs/<run_id>/
  run.json
  events.ndjson
  context-pack.md
  exec-plan.md
  verify-report.json
  review-report.json
  work-receipt.json
  run-diagnostics.json
  run-provenance.json
  claude-implement-prompt.md   # manual-first Claude
  claude-review-prompt.md
  codex-implement-prompt.md    # manual-first Codex
  codex-review-prompt.md
  rp-agent-implement-prompt.md   # manual RP handoff
  rp-agent-review-prompt.md
  rp-agent-implement-response.md # RP experimental auto/native
  rp-agent-review-response.md
  claude-implement-response.md   # Claude auto
  claude-review-response.md
```

`inspect` 会汇总当前状态、停止原因、next actions、契约边界与 evidence 导航信息。

## 默认 gates

默认 gate 集位于 `.ai/gates/default.yaml`，包含：

- `uv run ruff check src/ tests/`
- `uv run mypy src/aiwf/`
- `uv run pytest tests/ -x -q`

## Claude Code 技能

- `/rp-plan`
- `/rp-implement`
- `/rp-review`

## RP / Claude / Codex 编译投影

- `compile rp` 输出 `.rp/compiled/rp-bundle.md`、`rp-projection.json`、`install-surface.json`、`manifest.json`
- `compile claude` 输出 `.claude/compiled/claude-bundle.md`、`claude-projection.json`、`install-surface.json`、`manifest.json`
- `compile codex` 输出 `.codex/compiled/codex-bundle.md`、`codex-projection.json`、`install-surface.json`、`manifest.json`

这些编译目录都采用当前 install strategy：`use_compiled_output_directory`。`manifest.json` 包含 source fingerprint 与 drift 状态（`initial` / `clean` / `changed`）。

- 样例安装/集成方式见 `docs/INSTALL_GUIDE.md`
- 兼容性规则见 `docs/compatibility-policy.md`

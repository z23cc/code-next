# RepoPrompt Integration Checklist

本文档用于跟踪 `aiwf` 对接真实 RepoPrompt / `rp-cli` 的整体进度。

原则：

- 以 **bridge-first** 为主线，不假设真实 `rp-cli` 会实现 `aiwf-rp-native/v1`
- 每个阶段都有明确 exit criteria
- 只有前一阶段完成后，才进入下一阶段
- 外部依赖项单独标注，不与 in-repo 可交付项混淆

关联文档：

- `docs/RP_PROVIDER_GAP_ANALYSIS.md`
- `docs/RP_BRIDGE_DESIGN.md`
- `docs/RP_INTEGRATION_MATRIX.md`
- `docs/RP_CAPABILITY_INVENTORY.md`
- `docs/REPOPROMPT_CAPABILITY_INVENTORY.md`

---

## P0 — Consolidate bridge foundation

目标：把已完成的 bridge foundation 工作区改动收口为稳定基线。

- [x] 提交当前 working tree 中的 RP bridge foundation 改动（待本次 P0 baseline commit 落盘）
- [x] 跑通 `uv run aiwf contracts lint`
- [x] 跑通 `uv run pytest -q`
- [x] 确认 projection / compat fixture / run metadata fixture 全部对齐
- [x] 确认 docs 只描述已真实落地行为

Exit criteria:

- [x] bridge foundation 成为已提交、可验证的基线（验证已完成；提交见本文件更新后的 baseline commit）
- [x] 本地/CI 验证通过

Validation notes:

- 日期：2026-04-16
- 基线结论：当前 working tree 中的 RP bridge foundation diff 是单一、连贯的 P0 baseline；未发现需要启动 P1+ 才能解释的行为漂移。
- 已执行命令：`uv run aiwf contracts lint`；`uv run pytest -q`
- 结果：`contracts lint` 通过；pytest `188 passed`

---

## P1 — Manual-assist operator loop hardening

目标：让 `--bridge` manual-assist 在不调用真实 `rp-cli` 的前提下达到“可用”。

- [x] 在 diagnostics / inspect 中加入 bridge-specific summary
- [x] 补充 resume / review 对 `rp_bridge` 的完整 round-trip 测试
- [x] 增加 bridge contract downgrade / unsupported mode 负向测试
- [x] 明确 `--bridge` 的 operator next actions
- [x] 更新使用文档，给出清晰 manual-assist 操作步骤

Exit criteria:

- [x] bridge-enabled manual flow 可稳定运行
- [x] `inspect` 可清楚展示 bridge 状态与下一步
- [x] 文档可指导真实操作

Validation notes:

- 日期：2026-04-16
- P1 结论：manual-assist 现在已经达到“可用”门槛；`inspect`/`run-diagnostics.json` 会给出 bridge summary、handoff artifact 和 operator next actions，`resume` / `run review` 会稳定恢复同一份 `rp_bridge` metadata。
- 已执行命令：`uv run aiwf contracts lint`
- 已执行命令：`uv run pytest tests/test_engine.py tests/test_cli.py tests/test_adapter_contracts.py tests/test_adapter_rp.py tests/test_compile.py tests/test_doctor.py -q`
- 结果：`contracts lint` 通过；focused pytest `137 passed`

---

## P2 — Read-only rp-cli reconnaissance

目标：新增 `RpCliBridgeClient`，只做**只读**探测，不改外部 workspace 状态。

- [x] 新建 `RpCliBridgeClient`
- [x] 支持只读探测：binary / tool surface / workspace context probe
- [x] `doctor` 能显示 bridge tool surface 探测结果
- [x] `inspect --bridge-probe` 能展示 rp-cli 探测信息
- [x] 加入 fake `rp-cli` 测试覆盖 timeout / missing / malformed / success

Exit criteria:

- [x] 对真实/伪造 `rp-cli` 都能稳定做只读探测
- [x] 不引入任何 destructive 行为

Validation notes:

- 日期：2026-04-16
- P2 结论：`RpCliBridgeClient` 已提供 typed read-only probe result；`doctor` 与 `inspect --bridge-probe` 可以安全暴露 bridge tool surface，但不会把这类信号误表述为 real provider/runtime support。
- 已执行命令：`uv run pytest tests/test_rp_cli_bridge.py tests/test_doctor.py tests/test_cli.py -q`
- 已执行命令：`uv run aiwf contracts lint`
- 已执行命令：`uv run pytest tests/test_rp_cli_bridge.py tests/test_doctor.py tests/test_cli.py tests/test_adapter_contracts.py tests/test_adapter_rp.py tests/test_compile.py -q`
- 结果：focused pytest `60 passed`；final focused validation 中 `contracts lint` 通过，pytest `125 passed`

---

## P3 — Context seeding via MCP tools

目标：bridge 自动完成 RepoPrompt session 的上下文准备，但失败时必须安全回退。

- [x] 实现基于 `manage_selection` / `workspace_context` 的 bridge seeding 调用层（当前 slice 不要求真实 `bind_context`）
- [x] implement 阶段自动生成 `rp-bridge-seeding.json`
- [x] seeding 失败时仍保持 manual handoff 可用
- [x] provenance / inspect 中展示 seeding artifact
- [x] RP projection 增加 seeding artifact 合同字段并更新 compat fixture

Exit criteria:

- [x] `--bridge` 能自动准备 RepoPrompt 上下文（当前 scope：为 implement 手动交接预置 aiwf run artifacts）
- [x] 即使失败，也不会破坏 manual fallback

Validation notes:

- 日期：2026-04-16
- P3 结论：bridge-enabled implement 现在会尝试用 RepoPrompt MCP/tool surface 预置 `context-pack.md` / `exec-plan.md`，并把全过程写入 typed artifact `rp-bridge-seeding.json`。无论 bridge candidate 缺失、tool list 不兼容、`manage_selection` 失败还是返回 malformed data，run 都会保持原有 manual handoff 路径，只把失败写入 seeding artifact、diagnostics、inspect 与 provenance。
- 已执行命令：`uv run pytest tests/test_rp_cli_bridge.py tests/test_adapter_rp.py tests/test_engine.py tests/test_cli.py tests/test_compile.py tests/test_models.py tests/test_artifacts.py -q`
- 已执行命令：`uv run aiwf contracts lint`
- 已执行命令：`uv run pytest tests/test_rp_cli_bridge.py tests/test_adapter_rp.py tests/test_engine.py tests/test_cli.py tests/test_compile.py tests/test_models.py tests/test_artifacts.py tests/test_adapter_contracts.py tests/test_doctor.py -q`
- 结果：focused pytest `141 passed`；final focused validation 中 `contracts lint` 通过，pytest `174 passed`

---

## P4 — Response capture and normalization

目标：把 RepoPrompt 会话结果拉回 `aiwf`，并规范化为 run artifacts。

- [x] 新增 `aiwf rp bridge capture <run_id>`
- [x] implement capture 生成 `rp-agent-implement-response.md`
- [x] review capture 生成可校验的 `review-report.json`
- [x] normalization 逻辑 deterministic，不能伪造字段
- [x] end-to-end 测试覆盖 capture -> resume/review

Exit criteria:

- [x] operator 不需要手工整理 RepoPrompt 输出到 aiwf artifacts
- [x] review contract 在 happy path 下可自动满足

Validation notes:

- 日期：2026-04-16
- P4 结论：bridge manual-assist 现在可以通过只读 `read_file` surface 将 RepoPrompt 侧 implement/review 输出拉回 aiwf run，并分别落盘到 `rp-agent-implement-response.md`、`rp-agent-review-response.md`、`review-report.json` 与 `rp-bridge-capture.json`。review capture 在缺失 contract 必需字段时会 deterministic 地拒绝并保持 run `blocked`，不会伪造字段或破坏既有 manual fallback。
- 已执行命令：`uv run pytest tests/test_rp_cli_bridge.py tests/test_rp_bridge_normalize.py tests/test_artifacts.py tests/test_cli.py -q`
- 已执行命令：`uv run aiwf contracts lint`
- 已执行命令：`uv run pytest tests/test_engine.py tests/test_cli.py tests/test_rp_cli_bridge.py tests/test_rp_bridge_normalize.py tests/test_artifacts.py tests/test_adapter_contracts.py tests/test_adapter_rp.py tests/test_doctor.py -q`
- 结果：focused pytest `71 passed`；final focused validation 中 `contracts lint` 通过，pytest `154 passed`

---

## P5 — Managed-agent bridge mode

目标：通过 RepoPrompt `agent_run` 实现半自动/自动 bridge 流程。

- [ ] `BridgeMode` 扩展到 `managed-agent`
- [ ] CLI 支持 `--bridge-mode managed-agent`
- [ ] 对接 `agent_run start/wait/poll`
- [ ] `waiting_for_input` -> `blocked` 的状态映射稳定
- [ ] transcript / agent log / response artifacts 落盘
- [ ] projection contract 更新并补 compat fixture

Exit criteria:

- [ ] managed-agent 能稳定执行 implement/review 的可控子集
- [ ] timeout / failed / waiting_for_input 都有明确状态落盘

---

## P6 — Real runtime certification

目标：区分 reference-stub 信号与真实 RepoPrompt runtime 信号。

- [ ] conformance 输出增加 scope 标记
- [ ] `doctor` 区分 stub-like 与 real-runtime-like 探测结果
- [ ] 新增 `docs/RP_REAL_RUNTIME_VALIDATION.md`
- [ ] 形成真实 `rp-cli` 验证流程

Exit criteria:

- [ ] 用户不会把 stub 通过误读为真实 RepoPrompt 通过
- [ ] real-runtime 验证路径清晰、可重复

---

## 当前顺序

当前执行顺序固定为：

1. P0
2. P1
3. P2
4. P3
5. P4
6. P5
7. P6

当前阶段：

- [x] P0 completed
- [x] P1 completed
- [x] P2 completed
- [x] P3 completed
- [x] P4 completed
- [ ] P5 pending
- [ ] P6 pending

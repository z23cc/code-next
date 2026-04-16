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

- [ ] 在 diagnostics / inspect 中加入 bridge-specific summary
- [ ] 补充 resume / review 对 `rp_bridge` 的完整 round-trip 测试
- [ ] 增加 bridge contract downgrade / unsupported mode 负向测试
- [ ] 明确 `--bridge` 的 operator next actions
- [ ] 更新使用文档，给出清晰 manual-assist 操作步骤

Exit criteria:

- [ ] bridge-enabled manual flow 可稳定运行
- [ ] `inspect` 可清楚展示 bridge 状态与下一步
- [ ] 文档可指导真实操作

---

## P2 — Read-only rp-cli reconnaissance

目标：新增 `RpCliBridgeClient`，只做**只读**探测，不改外部 workspace 状态。

- [ ] 新建 `RpCliBridgeClient`
- [ ] 支持只读探测：binary / tool surface / workspace context probe
- [ ] `doctor` 能显示 bridge tool surface 探测结果
- [ ] `inspect --bridge-probe` 能展示 rp-cli 探测信息
- [ ] 加入 fake `rp-cli` 测试覆盖 timeout / missing / malformed / success

Exit criteria:

- [ ] 对真实/伪造 `rp-cli` 都能稳定做只读探测
- [ ] 不引入任何 destructive 行为

---

## P3 — Context seeding via MCP tools

目标：bridge 自动完成 RepoPrompt session 的上下文准备，但失败时必须安全回退。

- [ ] 实现 bind_context / manage_selection / workspace_context 的 bridge 调用层
- [ ] implement 阶段自动生成 `rp-bridge-seeding.json`
- [ ] seeding 失败时仍保持 manual handoff 可用
- [ ] provenance / inspect 中展示 seeding artifact
- [ ] RP projection 增加 seeding artifact 合同字段并更新 compat fixture

Exit criteria:

- [ ] `--bridge` 能自动准备 RepoPrompt 上下文
- [ ] 即使失败，也不会破坏 manual fallback

---

## P4 — Response capture and normalization

目标：把 RepoPrompt 会话结果拉回 `aiwf`，并规范化为 run artifacts。

- [ ] 新增 `aiwf rp bridge capture <run_id>`
- [ ] implement capture 生成 `rp-agent-implement-response.md`
- [ ] review capture 生成可校验的 `review-report.json`
- [ ] normalization 逻辑 deterministic，不能伪造字段
- [ ] end-to-end 测试覆盖 capture -> resume/review

Exit criteria:

- [ ] operator 不需要手工整理 RepoPrompt 输出到 aiwf artifacts
- [ ] review contract 在 happy path 下可自动满足

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
- [ ] P1 pending
- [ ] P2 pending
- [ ] P3 pending
- [ ] P4 pending
- [ ] P5 pending
- [ ] P6 pending

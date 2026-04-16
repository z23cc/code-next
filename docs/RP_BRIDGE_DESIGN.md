# RP Bridge Design (aiwf -> real rp-cli tool surface)

本文描述一个中期集成方向：

> 不要求真实 RepoPrompt CLI 实现 `aiwf-rp-native/v1`，而是在 `aiwf` 与真实 `rp-cli` 之间增加一层 **bridge**，通过 RepoPrompt 已有的 MCP/tool surface 间接完成 implement / review。

## 1. 设计目标

目标不是改造外部 RepoPrompt CLI，而是：

- 复用真实 `rp-cli` 已有的 workspace / context / agent 能力
- 避开对 `--aiwf-protocol-version` 和 stdin/stdout envelope 的强依赖
- 让 `aiwf` 仍然保持：
  - run 状态管理
  - diagnostics / provenance
  - gate / review 契约
  - `resume` / `inspect` 语义

换句话说：

- `aiwf` 继续做 **workflow kernel**
- RepoPrompt 继续做 **宿主 / 编排运行面**
- bridge 负责做 **意图翻译与结果回填**

## 2. 非目标

当前 bridge 设计**不试图**：

- 修改真实 RepoPrompt CLI
- 强行让真实 `rp-cli` 说 `aiwf-rp-native/v1`
- 让所有 RP workflow 一步到位变成全自动
- 取代当前稳定的 manual handoff 路径

manual-first 仍然应保留为 fallback。

## 3. 高层架构

```text
aiwf
  └─ RP bridge runner
       ├─ resolve RepoPrompt workspace/tab/context
       ├─ publish aiwf run artifacts as RepoPrompt-consumable context
       ├─ call rp-cli MCP/tool surfaces
       ├─ wait/poll/extract results
       └─ normalize output back into aiwf artifacts
            ├─ rp-agent-implement-response.md
            ├─ rp-agent-review-response.md
            ├─ work-receipt.json
            └─ review-report.json / diagnostics metadata
```

核心思想是：

- `aiwf` 不再把 RP 看成“一个会返回字符串的子进程”
- 而是看成“一个需要被驱动的外部宿主会话”

## 4. 可利用的真实 RepoPrompt CLI 能力

基于已验证能力，bridge 可优先依赖这些入口：

- `manage_workspaces`
- `bind_context`
- `manage_selection`
- `workspace_context`
- `context_builder`
- `ask_oracle`
- `agent_run`
- `agent_manage`
- `read_file`
- `file_search`

这些能力足以支撑：

- 定位或创建会话
- 构建上下文
- 发起 implement/review 请求
- 轮询 agent 状态
- 导出 transcript / handoff / 日志

## 5. 建议的 bridge 模式

建议分两级，而不是一上来追求单一路径：

### A. `bridge/manual-assist`

特点：

- bridge 帮你自动完成 workspace/tab/context 准备
- 自动把 `context-pack.md` / `exec-plan.md` / compiled RP bundle 组织进 RepoPrompt 工作区上下文
- 自动生成并发送第一条 implement/review 指令
- 如果进入需要人工判断的状态，就回退为 `blocked`

适合：

- 先减少手工准备成本
- 保持当前 manual-first 契约不变

### B. `bridge/managed-agent`

特点：

- bridge 使用 `agent_run` / `agent_manage`
- 自动启动 agent、等待、轮询、收集结果
- 将终态结果回填到 `aiwf` artifacts

适合：

- 在 RepoPrompt agent 行为足够稳定后，推进半自动 / 准自动实现

## 6. implement 阶段建议流程

## 6.1 输入

bridge 的最小输入建议来自 `aiwf` 已有产物：

- `.ai/runs/<run_id>/context-pack.md`
- `.ai/runs/<run_id>/exec-plan.md`
- task frontmatter / task body
- `.rp/compiled/` 下的：
  - `rp-bundle.md`
  - `rp-projection.json`
  - `install-surface.json`
  - `manifest.json`

## 6.2 流程

1. **resolve workspace**
   - 用 `manage_workspaces` / `bind_context` 解析目标 RepoPrompt workspace / tab
2. **prepare selection**
   - 用 `manage_selection` 选中：
     - 当前任务相关源码
     - `context-pack.md`
     - `exec-plan.md`
     - 必要的 compiled RP bundle
3. **seed prompt**
   - 用 `ask_oracle` 或 `agent_run start`
   - 指令内容不是原始 provider prompt，而是：
     - “你正在为 aiwf 的 implement 阶段工作”
     - “以 `.ai/runs/<run_id>/...` 中的计划与上下文为准”
     - “输出简明实现总结”
4. **wait / poll**
   - 用 `agent_run wait/poll`
   - 若进入 `waiting_for_input`，bridge 可：
     - 回写 `blocked`
     - 生成 operator next steps
5. **extract result**
   - 用 `agent_manage.get_log` / `extract_handoff`
   - 或使用 `ask_oracle export_response`
6. **normalize back**
   - 回填：
     - `rp-agent-implement-response.md`
     - `work-receipt.json`
     - 需要时更新 `run-diagnostics.json` 中的 next actions / evidence

## 6.3 implement 阶段产物映射

| RepoPrompt side | aiwf side |
| --- | --- |
| agent final response / handoff summary | `rp-agent-implement-response.md` |
| agent transcript / logs | provenance attachment or linked artifact |
| session_id / context_id | diagnostics metadata |
| blocked / waiting_input state | `status=blocked` + `resume_command` |

## 7. review 阶段建议流程

review 与 implement 相同，但输入面要更偏向证据：

- `verify-report.json`
- changed files summary
- git diff / selected files
- review contract 要求的字段

建议流程：

1. 绑定相同 workspace/tab
2. 将 run artifacts 和 diff 证据加入 selection
3. 用 `agent_run` 或 `ask_oracle review` 发起 review
4. 采集结果
5. 规范化为：
   - `rp-agent-review-response.md`
   - `review-report.json`

关键不是“原样复制聊天内容”，而是：

- 让 bridge 输出满足 `aiwf` review contract 的规范化结果

## 8. bridge 需要的新配置面

如果后续在 `aiwf` 中实现 bridge，建议显式引入以下配置：

| 配置 | 用途 |
| --- | --- |
| `rp_bridge.enabled` | 显式启用 bridge 模式 |
| `rp_bridge.workspace` | 指定 RepoPrompt workspace |
| `rp_bridge.tab` | 指定或创建目标 tab |
| `rp_bridge.context_id` | 直接绑定 compose context |
| `rp_bridge.mode` | `manual-assist` / `managed-agent` |
| `rp_bridge.agent_role` | `pair` / `engineer` / `explore` 等 |
| `rp_bridge.timeout_seconds` | wait/poll 上限 |
| `rp_bridge.export_transcript` | 是否导出 transcript/handoff 作为 artifact |

这样可以避免把 bridge 误塞进当前 `NativeRuntimeContract` 的 provider 语义里。

## 9. 为什么 bridge 比 provider 更现实

bridge 更现实，原因有三点：

1. **尊重外部工具原生模型**
   - 真实 RepoPrompt CLI 已经是 workspace/agent orchestration 工具
   - 不是 subprocess envelope runtime
2. **不要求外部改造**
   - 你只是“拿来用”，不是维护者
3. **更符合已验证能力**
   - 已确认 RepoPrompt 强在：
     - selection/context
     - chat/oracle
     - agent_run / agent_manage

而这些正好是 bridge 最需要的能力

## 10. 主要风险

### 风险 1：会话绑定不稳定

- 多 workspace / 多 tab / 多窗口时，bridge 可能绑错上下文

缓解：

- 优先支持显式 `context_id`
- 其次才是 workspace + tab 解析

### 风险 2：agent 输出不可直接映射为 aiwf 契约

- RepoPrompt 侧输出天然是对话/agent transcript
- `aiwf` 需要规范化 artifact

缓解：

- bridge 必须做“结果规范化”，不能直接把 transcript 当 review-report

### 风险 3：长流程需要人工审批

- `agent_run` 可能进入 `waiting_for_input`

缓解：

- 在 `manual-assist` 模式下，把这类状态显式回写为 `blocked`

### 风险 4：上下文漂移

- RepoPrompt workspace selection 可能与 `aiwf` 当前 run 语义脱钩

缓解：

- 每次 stage 前由 bridge 明确重建 selection
- 使用 run artifacts 作为稳定 source of truth

## 11. 推荐落地顺序

### Phase 1 — manual-assist hardening（已落地）

> **Status (2026-04-16): P1 completed.** 当前已落地的是 `--bridge` manual-assist 的 operator hardening：`rp_bridge` run metadata 持久化、implement/review prompt 中的 bridge context 重放、`resume`/`run review` 的 bridge restore、`inspect` / `run-diagnostics.json` 中的 bridge summary + next actions，以及对 contract downgrade / unsupported bridge mode 的 fail-fast 校验。**当前仍然不会调用 rp-cli MCP/tools**。

当前可用的 manual-assist 语义是：

- operator 手动决定 RepoPrompt workspace / tab / context
- `aiwf` 把这些提示写入 `rp_bridge` metadata
- implement 阶段把提示写进 `rp-agent-implement-prompt.md`
- `inspect` 明确显示 bridge summary、handoff artifact、以及下一步 `resume` / `run review` 指令
- review 阶段恢复同一份 bridge 配置，并重新写进 `rp-agent-review-prompt.md`
- 如果后续 stored host contract 不再支持 bridge，或不再支持 `manual-assist`，restore 会直接失败，而不是悄悄降级

一个最小 operator loop 是：

1. `uv run aiwf run implement --adapter rp --bridge ...`
2. 在指定 RepoPrompt 会话中按 `rp-agent-implement-prompt.md` 完成实现
3. `uv run aiwf resume <run_id>`
4. `uv run aiwf run review --run-id <run_id>`
5. 在同一 RepoPrompt 会话中按 `rp-agent-review-prompt.md` 完成 review
6. `uv run aiwf resume <run_id>`

### Phase 2 — 只读 rp-cli reconnaissance（已落地）

> **Status (2026-04-16): P2 completed.** 当前已落地的是一个只读 `RpCliBridgeClient`，它只做 bridge reconnaissance：探测 command candidate、读取 tool surface、读取 workspace context，并把成功/缺失/超时/非零退出/ malformed JSON 统一映射成 typed result。`doctor` 会把 bridge tool probe 结果作为 **bridge readiness hint** 暴露出来，`inspect --bridge-probe` 也可以按需运行同样的只读 probe。**这些结果不代表 `aiwf-rp-native/v1` provider 支持，也不会修改任何外部 workspace state。**

当前 P2 的实际能力是：

- `RpCliBridgeClient.from_command_candidates(...)`
- `RpCliBridgeClient.probe_available()`
- `RpCliBridgeClient.list_tools()`
- `RpCliBridgeClient.workspace_context(...)`
- `doctor` 中的 bridge tool probe surface
- `inspect --bridge-probe` 的 opt-in probe surface

当前 P2 的明确边界仍然是：

- 不会调用 mutating MCP/tool API
- 不会自动 bind workspace / context
- 不会准备 selection / seeding context
- 不会 capture transcript / handoff
- 不会启动 managed-agent

也就是说，P2 只是把“机器上有没有一个可读的 RepoPrompt bridge candidate，以及它大概暴露了什么只读 surface”这件事安全地说清楚。

### Phase 3+

再之后才考虑：

- context seeding / selection automation
- capture / transcript normalization
- managed-agent bridge
- 更深的 `inspect` / provenance / review contract 自动化

## 12. 一句话结论

如果真实 RepoPrompt CLI 不是 `aiwf` provider，最佳路线不是硬凑 provider 协议，  
而是增加一层 **bridge**，把 `aiwf` 的 stage 意图翻译成 RepoPrompt 已经擅长的 workspace / context / agent 操作，再把结果安全回填成 `aiwf` artifacts。

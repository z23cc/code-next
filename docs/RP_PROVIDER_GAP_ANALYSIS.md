# RepoPrompt CLI vs aiwf Provider Gap Analysis

本文聚焦一个具体问题：

> 真实 RepoPrompt CLI（`rp-cli`）当前是否可以直接充当 `aiwf` 的 RP native provider？

结论先行：

- **不能直接等同。**
- 真实 RepoPrompt CLI 已经具备很强的 workspace / MCP tool / agent orchestration 能力。
- 但它当前暴露的是**宿主/编排型 CLI**，不是 `aiwf` 期待的**无状态 provider 子进程协议端**。
- 因此，当前最稳妥的集成策略仍是 **manual-first**；中期更值得做的是 **bridge**，而不是继续假定真实 `rp-cli` 已经实现 `aiwf-rp-native/v1`。

## 1. 验证快照

本结论基于一次本地真实验证快照（2026-04-16）：

- 真实 RepoPrompt CLI：
  - `/usr/local/bin/rp-cli -> /Applications/Repo Prompt.app/Contents/MacOS/repoprompt-mcp`
- 参考协议 harness：
  - `.venv/bin/rp-cli`
  - 该二进制来自仓库测试环境，用于 `aiwf-rp-native/v1` 协议/CI 演练

实际验证结果：

1. `rp-cli --list-tools`
   - 成功，显示 RepoPrompt MCP tools
2. `rp-cli --aiwf-protocol-version`
   - **失败**
   - 真实 `rp-cli` 不返回 `aiwf-rp-native` probe payload，而是报“no command or mode specified”
3. `uv run aiwf conformance rp --rp-command /usr/local/bin/rp-cli --json`
   - **失败于 probe**
4. 在只保留真实 `rp-cli` 的 PATH 下运行：
   - `python -m aiwf doctor --json`
   - `rp` 检查结果为：**runtime found, but protocol negotiation support was not detected**
5. 同样在只保留真实 `rp-cli` 的 PATH 下运行：
   - `python -m aiwf run implement --adapter rp`
   - 正确停在 **manual handoff** 边界，并生成 `rp-agent-implement-prompt.md`

这组验证说明：

- 真实 RepoPrompt CLI 的**宿主能力**是真实存在的
- 但它**不是**当前 `aiwf` 所需的 RP native provider

## 2. 双方接口模型的根本差异

### `aiwf` 当前期待的 provider 形态

`aiwf` 在 `src/aiwf/adapters/rp_agent.py` 与 `docs/RP_NATIVE_PROTOCOL.md` 中期待：

- 一个可 probe 的命令：
  - `--aiwf-protocol-version`
- 一次调用处理一次 stage：
  - `plan`
  - `implement`
  - `review`
- 通过 stdin 接收 JSON envelope
- 通过 stdout 返回 JSON envelope
- 进程是**无状态、单请求、可作为 subprocess callee** 的

### 真实 RepoPrompt CLI 当前呈现的形态

真实 `rp-cli` 当前暴露的是：

- `-e '<command>'` 的命令式执行面
- `-c <tool> -j <json>` 的 MCP tool 调用面
- workspace / window / tab / context 绑定模型
- selection / context_builder / ask_oracle / agent_run / agent_manage 等能力

也就是说，它是：

> **一个面向工作区、上下文和 agent 编排的宿主 CLI**

而不是：

> **一个单次请求、无状态的 provider 子进程**

## 3. 差距矩阵

| 维度 | `aiwf` provider 期待 | 真实 RepoPrompt CLI 当前能力 | 差距判断 |
| --- | --- | --- | --- |
| Probe | `--aiwf-protocol-version` 返回协议 JSON | 无此行为；直接进入自身 CLI 参数解析 | **硬缺口** |
| 调用模型 | 一次 subprocess = 一次 stage 请求 | 需要 workspace / tab / context 绑定 | **模型不匹配** |
| 输入协议 | stdin JSON envelope | `-e` / `-c -j` 命令调用 | **传输层不匹配** |
| 输出协议 | stdout JSON envelope（`ok/error/partial`） | 普通 CLI 输出 / tool 输出 | **返回格式不匹配** |
| 生命周期 | stateless callee | workspace-scoped orchestrator | **状态模型不匹配** |
| 能力定位 | 执行器 | 宿主 / 编排器 / 工作区入口 | **产品角色不同** |
| 错误语义 | `UNSUPPORTED_VERSION` / `EXECUTION_TIMEOUT` / `partial` 等 | 没有证据表明遵循 `aiwf-rp-native/v1` 错误面 | **协议语义未对齐** |
| 兼容回退 | probe 失败后回到 legacy text runtime | 可作为人工/宿主入口，但不是 legacy provider | **只能回退到 manual-first** |

## 4. 已证实可依赖的 RepoPrompt CLI 能力

虽然它不是 provider，但真实 RepoPrompt CLI 已证实具备以下高价值能力：

- `file_search`
- `read_file`
- `get_file_tree`
- `manage_selection`
- `workspace_context`
- `ask_oracle`
- `agent_run`
- `agent_manage`
- workspace / tab / context 绑定与切换

这说明它更适合承接：

- 上下文构建
- 任务分解与 agent 调度
- 手动/半自动 handoff
- 结果提取与日志收集

而不是直接承接：

- `aiwf` 的 native provider envelope 协议

## 5. 对 `aiwf` 当前策略的含义

### 当前稳定成立的 RP 路径

- `compile rp`
- `rp-bundle.md`
- `rp-projection.json`
- `install-surface.json`
- manual prompt handoff
- `resume`
- `inspect`
- review evidence / host contract 恢复

### 当前不应过度解读的信号

- `doctor` 检测到 protocol v1
  - 可能只是检测到了仓库内 stub，而不是真实 RepoPrompt CLI
- `conformance rp` 在本仓库环境通过
  - 证明的是 `aiwf` 与 reference harness 的协议一致性
  - 不是对真实 RepoPrompt app / CLI 的认证

## 6. 决策建议

### 短期

把真实 RepoPrompt CLI 视为：

- **宿主 / 编排平台**
- 不是 `aiwf` 的 native provider

因此，RP 官方稳定路径仍应表述为：

- **manual-first**
- `compile rp` + handoff prompt + `resume`

### 中期

优先设计并验证：

- **bridge-based integration**

即：

- `aiwf` 不直接把真实 `rp-cli` 当 protocol callee
- 而是通过其 MCP/tool surface **间接驱动** implement / review

### 长期

只有在 RepoPrompt 侧明确愿意支持时，才考虑：

- 真正的 `aiwf-rp-native/v1` provider mode
- 即新增专门的 probe / envelope / response / error contract 支持

## 7. 一句话结论

真实 RepoPrompt CLI **已经足够强大，值得集成**；  
但它当前适合被 `aiwf` 当作 **宿主能力入口** 来利用，而不是被误判为已经实现了 `aiwf` native provider 协议的运行时。

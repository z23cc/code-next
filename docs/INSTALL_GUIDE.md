# 安装与集成指南（RP + Claude）

本文说明当前 `aiwf` 的宿主 compile/install surface 应该如何被真实消费。它不假设额外的样例仓库，直接基于本仓库当前已经实现的输出语义。

当前 guide 覆盖：

- RepoPrompt（`rp`）
- Claude Code（`claude`）

> **当前产品口径：** `aiwf` 的唯一官方 RP target 是真实 RepoPrompt app / MCP CLI runtime。当前稳定、推荐的 RP 使用方式仍是 manual handoff + `resume`；仓库内的 `rp-cli-stub` 仅用于参考协议/CI 测试，不等于真实 RepoPrompt 运行时就绪。

如果你只想知道兼容性边界，请看 `docs/compatibility-policy.md`。如果你想从零跑一个任务，请先看 `docs/QUICKSTART.md`。

如果你想理解为什么真实 RepoPrompt CLI 目前更适合作为宿主能力入口、而不是直接当作 `aiwf-rp-native/v1` provider，请看：

- `docs/RP_PROVIDER_GAP_ANALYSIS.md`
- `docs/RP_BRIDGE_DESIGN.md`

## 1. 先理解当前“install”语义

当前 compile 产物的安装语义不是“发布到包仓库”或“复制到某个隐藏目录”，而是：

- 运行 `uv run aiwf compile <host> --output <dir>`
- 得到一个可直接保存在该输出目录中的宿主 bundle
- 由 `install-surface.json` 声明该目录里的哪些文件由 compiler 管理
- 由 `*-projection.json` 声明宿主命令、host contract、review contract、resume 边界
- 由 `manifest.json` 提供 source fingerprint 与 drift 信息

也就是说，当前 install strategy 是：

- `install_strategy = "use_compiled_output_directory"`

实践上，消费方应把整个编译输出目录当作一个稳定 bundle，而不是只拿其中单个文件。

## 2. 输出里每个文件是干什么的

无论是 RP 还是 Claude，当前 compile 都会输出 4 个核心文件：

- `*-bundle.md`：给宿主/操作者直接阅读和消费的 bundle
- `*-projection.json`：给自动化脚本、集成层、检查工具读取的显式宿主投影
- `install-surface.json`：声明当前输出目录的安装/所有权语义
- `manifest.json`：记录 source fingerprint、输出 hash、drift 状态

推荐的读取顺序是：

1. 先看 `install-surface.json`，确认目录所有权和 generated assets
2. 再看 `*-projection.json`，确认当前宿主支持的 variant、命令与 workflow 边界
3. 最后把 `*-bundle.md` 交给对应宿主/操作者使用

## 3. RepoPrompt（RP）集成示例

### 3.1 生成 RP bundle

```bash
uv run aiwf compile rp --output .rp/compiled
```

当前真实输出文件名：

```text
.rp/compiled/
  rp-bundle.md
  rp-projection.json
  install-surface.json
  manifest.json
```

CLI 会打印类似：

```text
compile completed bundle=.rp/compiled/rp-bundle.md
projection=.rp/compiled/rp-projection.json
install=.rp/compiled/install-surface.json
manifest=.rp/compiled/manifest.json drift=initial
```

### 3.2 如何消费 RP install surface

当前 RP 的 `install-surface.json` 语义是：

- `install_strategy` = `use_compiled_output_directory`
- `default_output_dir` = `.rp/compiled`
- compiler 管理 4 个 generated assets：
  - `rp-bundle.md`
  - `rp-projection.json`
  - `install-surface.json`
  - `manifest.json`
- `external_assets` 为空

这意味着：

- 不需要再把 RP bundle 拷贝到别的安装位置
- 直接保留 `.rp/compiled/` 整个目录即可
- 如果后续重新 compile，这 4 个文件都属于 compiler-managed surface

### 3.3 如何消费 RP projection

`rp-projection.json` 是 RP 集成的机器可读入口。当前重点字段：

- `host.stored_runtime_key = "host_contract"`
- `host.default_variant = "rp/manual"`
- `host.variants.manual`
- `host.variants.auto`
- `workflow_contract.plan.entrypoint`
- `workflow_contract.plan.auto_entrypoint`
- `workflow_contract.implement.manual_handoff_artifact = "rp-agent-implement-prompt.md"`
- `workflow_contract.implement.auto_stage_output_artifact = "rp-agent-implement-response.md"`
- `workflow_contract.implement.auto_entrypoint`
- `workflow_contract.review.report_contract.manual`
- `workflow_contract.review.report_contract.auto`
- `workflow_contract.resume.restores_run_metadata = ["host_contract"]`

当前 `rp-projection.json` 仍暴露 `manual` 与 `auto` 两个 variant，因为实现层还保留了兼容性与实验性 native path。但产品口径应按下面理解：

- 稳定、默认、推荐路径：RP manual handoff + `resume`
- 唯一官方 RP target：真实 RepoPrompt app / MCP CLI runtime
- `rp-cli-stub` 只是 reference test harness，用于 CI / conformance 演练，不等于真实 RepoPrompt runtime readiness
- `--auto` 仅应在你已验证真实 RepoPrompt runtime 实现了 `aiwf-rp-native/v1` 时尝试
- 即使 native runtime 不可用，manual handoff 仍然是支持路径

### 3.4 RP 的实际消费方式

#### 稳定 manual handoff 路径（推荐）

如果你当前是在真实项目/产品上下文里把 compile 输出交给 RepoPrompt 使用，这应该是默认路径：

```bash
uv run aiwf run plan --task .ai/tasks/<task>.md --adapter rp
uv run aiwf run implement --task .ai/tasks/<task>.md --adapter rp
uv run aiwf resume <run_id>
uv run aiwf run review --run-id <run_id>
uv run aiwf resume <run_id>
```

这条路径下，运行目录中的关键 RP artifacts 通常是：

- `rp-agent-implement-prompt.md`
- `rp-agent-review-prompt.md`

还可以在 RP manual 模式下显式加 `--bridge`（以及可选的 `--bridge-workspace` / `--bridge-tab` / `--bridge-context-id` / `--bridge-agent-role` 等参数）启用**实验性的 manual-assist groundwork**。在当前 slice 中，这只会为 manual prompt artifact 增加 bridge context 并持久化 `rp_bridge` metadata；**不会调用 rp-cli MCP/tools**，也不会改变稳定的 manual artifact 名称或 review contract。

#### 实验性 auto 路径（仅限已验证的真实 RepoPrompt runtime）

> **Experimental status:** 只有当机器上的 `rp` 或 `rp-cli` 确认就是实现了 `aiwf-rp-native/v1` 的真实 RepoPrompt app / MCP CLI runtime 时，才应尝试这条路径。仓库内的 `rp-cli-stub` 仅用于协议测试；CI 中的 stub conformance 也不代表真实运行时 readiness。

如果你明确要验证上述真实运行时，可以按 projection 中声明的 auto entrypoint 使用：

```bash
uv run aiwf run plan --task .ai/tasks/<task>.md --adapter rp --auto
uv run aiwf run implement --task .ai/tasks/<task>.md --adapter rp --auto
uv run aiwf run review --run-id <run_id>
```

这条路径下，关键输出会变成 response artifacts，例如：

- `rp-agent-implement-response.md`
- `rp-agent-review-response.md`

review contract 也会从 manual 的 `prompt_file` 切换到 auto 的 `response_file`。

> **Protocol note:** `aiwf` 与 RP native runtime 的结构化 I/O 协议定义见 `docs/RP_NATIVE_PROTOCOL.md`。该文档的 reference stub 仅用于测试协议面；产品层面的官方目标仍是真实 RepoPrompt app / MCP CLI runtime。

### 3.5 RP bundle 给谁看

- 人工操作者：直接读 `rp-bundle.md`
- 集成脚本/工具：读 `rp-projection.json` 与 `install-surface.json`
- 变更检测/缓存系统：读 `manifest.json`

## 4. Claude Code 集成示例

### 4.1 生成 Claude bundle

```bash
uv run aiwf compile claude --output .claude/compiled
```

当前真实输出文件名：

```text
.claude/compiled/
  claude-bundle.md
  claude-projection.json
  install-surface.json
  manifest.json
```

CLI 会打印类似：

```text
compile completed bundle=.claude/compiled/claude-bundle.md
projection=.claude/compiled/claude-projection.json
install=.claude/compiled/install-surface.json
manifest=.claude/compiled/manifest.json drift=initial
```

### 4.2 如何消费 Claude install surface

Claude 的 install surface 和 RP 类似，也采用：

- `install_strategy = "use_compiled_output_directory"`
- compiler 管理 `.claude/compiled/` 下的 4 个 generated assets

但 Claude 还有一个重要差异：

- `external_assets` 当前显式声明了 `.claude/skills`
- 其 owner 是 `handwritten`
- `managed_by_compiler = false`

这意味着：

- compile 只拥有 `.claude/compiled/` 下的生成文件
- `.claude/skills` 仍然是手写入口，不应被 compiler 覆盖或当成 generated surface

### 4.3 如何消费 Claude projection

`claude-projection.json` 当前声明：

- `host.default_variant = "claude/manual"`
- Claude 支持 `manual` 与 `auto` 两个 variant
- `workflow_contract.implement.manual_handoff_artifact = "claude-implement-prompt.md"`
- review contract 在 manual 模式下链接 `prompt_file`
- review contract 在 auto 模式下链接 `response_file`
- `resume` 会恢复 `host_contract`

### 4.4 Claude 的实际消费方式

#### 手动 Claude 路径

```bash
uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude
uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude
uv run aiwf resume <run_id>
uv run aiwf run review --run-id <run_id>
uv run aiwf resume <run_id>
```

关键 artifacts：

- `claude-implement-prompt.md`
- `claude-review-prompt.md`

#### Claude auto 路径

```bash
uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude --auto
uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude --auto
uv run aiwf run review --run-id <run_id>
```

关键 artifacts：

- `claude-implement-response.md`
- `claude-review-response.md`

和 RP 一样，auto 模式下的 review linked artifact 是 `response_file`，不是 `prompt_file`。

## 5. 一个最小、可信的消费模式

如果你要把 compile surface 接到外层工具里，当前最实用的规则是：

### 5.1 人工消费

- 读取 `*-bundle.md`
- 按 `*-projection.json` 里的命令入口运行 `plan / implement / review / resume`
- 遇到 manual handoff 时，使用 projection 中声明的 handoff artifact 名称

### 5.2 机器消费

- 用 `install-surface.json` 判断哪些文件属于 compiler-managed output
- 用 `*-projection.json` 判断：
  - 默认 variant
  - 是否支持 auto
  - manual/auto 的 review contract 差异
  - run review 前需要哪些 artifacts
  - resume 恢复哪些 runtime metadata
- 用 `manifest.json` 判断当前 bundle 是否相对上次 compile 发生 drift

### 5.3 不要这样消费

当前不推荐：

- 只复制 `*-bundle.md` 而忽略 projection/install surface
- 手写推断某个宿主是否支持 auto，而不读取 `host.variants`
- 手写猜测 review 链接证据是 `prompt_file` 还是 `response_file`
- 把 `.claude/skills` 当成 compiler-managed generated output

## 6. 快速自检命令

编译后，你可以快速检查 surface：

```bash
cat .rp/compiled/install-surface.json
cat .rp/compiled/rp-projection.json
cat .claude/compiled/install-surface.json
cat .claude/compiled/claude-projection.json
```

如果只想验证 compile 是否正常：

```bash
uv run aiwf compile rp --output .rp/compiled
uv run aiwf compile claude --output .claude/compiled
```

如果只想验证后续运行边界是否符合 projection：

```bash
uv run pytest tests/test_compile.py tests/test_adapter_contracts.py -q
```

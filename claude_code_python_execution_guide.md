# Claude Code 执行文档（Python 版）

这份文档面向两个目标：

1. 你可以直接读它，理解为什么 Python 是当前最稳的实现路径。
2. 你可以把配套文件交给 Claude Code，让它按统一规范去实现 `aiwf` 工作流内核。

## 核心判断

这个方案的重心不是做一个很重的 Claude 专属插件，而是先实现一个 **Python 工作流内核**，再用 Claude Code 的 `CLAUDE.md` 与 skills 作为执行入口。  
这样做的好处是：

- 真源在 `.ai/`，不会被宿主锁死
- Claude Code 只做薄适配，后面迁移到其他宿主成本低
- Python 非常适合状态机、CLI、YAML/JSON、subprocess、artifact 管理
- 第一版可以尽快把 `plan -> implement -> review -> resume` 跑通

## 交付物说明

配套压缩包里已经包含：

- `CLAUDE.md`
- `.claude/skills/rp-plan/SKILL.md`
- `.claude/skills/rp-implement/SKILL.md`
- `.claude/skills/rp-review/SKILL.md`
- `.ai/` 真源目录
- `docs/PYTHON_IMPLEMENTATION_SPEC.md`
- `pyproject.toml.example`

## 最推荐的使用方式

把压缩包内容复制到你的仓库根目录，然后：

1. 修改 `.ai/policies/repo-policy.md`
2. 修改 `.ai/gates/default.yaml`
3. 基于 `.ai/tasks/TEMPLATE.md` 创建真实任务
4. 启动 Claude Code
5. 先执行 `/rp-plan`
6. 再执行 `/rp-implement`
7. 最后执行 `/rp-review`

## 你真正应该交给 Claude Code 的文件

真正给 Claude Code 执行的核心不是这份说明本身，而是：

- `CLAUDE.md`
- `.claude/skills/*`
- `.ai/*`

也就是说，这套包里最关键的是“可执行的仓库内约束”，不是“说明文字”。

## 结构简述

- `CLAUDE.md`：长期稳定规则
- `skills`：多步流程
- `.ai/runbooks`：工作流语义
- `.ai/gates`：校验命令
- `.ai/tasks`：任务输入
- `.ai/runs`：运行状态与产物

## 建议你先让 Claude Code 实现的第一批能力

- `TaskSpec`
- `RunbookSpec`
- `GateSet`
- `RunState`
- `ArtifactStore`
- `aiwf run plan`
- `aiwf run implement`
- `aiwf resume`

## 结论

这套文件不是“概念 PPT”，而是能直接进入仓库、能被 Claude Code 使用、且以后还能扩成更完整 Python 内核的第一版骨架。

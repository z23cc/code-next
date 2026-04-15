---
name: default
description: Default runbook for the current aiwf workflow contract.
stages:
  - name: discover
    description: Gather task, policy, and repository context for the run.
    required: true
    retry_limit: 0
    outputs:
      - context-pack.md
  - name: plan
    description: Produce the execution plan artifact for the run.
    required: true
    retry_limit: 0
    outputs:
      - exec-plan.md
  - name: implement
    description: Reach the implementation boundary, which may stop at a manual host handoff or continue through gates.
    required: true
    retry_limit: 0
    pause_on:
      - blocked
      - needs_review
    outputs:
      - claude-implement-prompt.md
      - codex-implement-prompt.md
      - rp-agent-implement-prompt.md
      - verify-report.json
  - name: review
    description: Review an existing implementation run after gates, which may also stop at a manual host handoff before finalization.
    required: true
    retry_limit: 0
    pause_on:
      - blocked
    outputs:
      - claude-review-prompt.md
      - codex-review-prompt.md
      - rp-agent-review-prompt.md
      - review-report.json
      - work-receipt.json
---

# Default Runbook

Use this runbook when no task-specific workflow overrides are required.

This file documents expected stage boundaries, strategy defaults (`required`, `retry_limit`, `pause_on`), artifact shape, and operator handoff points for the default workflow.
It is loaded and validated by the engine, but it does **not** fully drive branching or status-transition control flow on its own today.
The engine still owns the concrete `plan / implement / review / resume` control logic; the runbook is the workflow-facing contract description for that logic.

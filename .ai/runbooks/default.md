---
name: default
description: Default runbook for the Phase 1 aiwf workflow kernel.
stages:
  - name: discover
    description: Gather the task, policy, and repository context.
    outputs:
      - context-pack.md
  - name: plan
    description: Produce an execution plan for the selected task.
    outputs:
      - exec-plan.md
  - name: implement
    description: Apply code changes and prepare them for validation.
    outputs:
      - work-receipt.json
  - name: review
    description: Review results and record any follow-up items.
    outputs:
      - review-report.json
---

# Default Runbook

Use this runbook when no task-specific workflow overrides are required.

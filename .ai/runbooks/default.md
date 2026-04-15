---
name: default
description: Default runbook for the aiwf kernel's current phase-2 workflow contract.
stages:
  - name: discover
    description: Gather task, policy, and repository context for the run.
    outputs:
      - context-pack.md
  - name: plan
    description: Produce the execution plan artifact for the run.
    outputs:
      - exec-plan.md
  - name: implement
    description: Reach the implementation boundary, which may stop at a manual Claude handoff or continue through gates.
    outputs:
      - claude-implement-prompt.md
      - verify-report.json
  - name: review
    description: Review an existing implementation run after gates, which may also stop at a manual Claude handoff before finalization.
    outputs:
      - review-report.json
      - work-receipt.json
---

# Default Runbook

Use this runbook when no task-specific workflow overrides are required.

This file currently documents the expected stage boundaries, artifact shape, and operator handoff points for the default workflow.
It is loaded and validated by the engine, but it does **not** fully drive branching or status-transition control flow on its own today.
The engine still owns the concrete `plan / implement / review / resume` control logic; the runbook is the workflow-facing contract description for that logic.

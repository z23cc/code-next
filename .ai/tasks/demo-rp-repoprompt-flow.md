---
title: Demo RP RepoPrompt flow validation
slug: demo-rp-repoprompt-flow
runbook: default
gates: default
policy: repo-policy
---

# Goal

Demonstrate a real `aiwf` run with the RepoPrompt (`rp`) adapter in this repository.
Validate the workflow path using the local environment and produce only run artifacts for the demonstration.

# Constraints

- Demonstration only; do not modify product code.
- Do not change files under `src/`, `tests/`, `docs/`, or other tracked product areas.
- Creating this task file under `.ai/tasks/` and generating `.ai/runs/` artifacts is allowed.
- Prefer RP native/auto execution if the local environment truly supports it.
- If RP auto/native is unavailable, stop at the correct manual handoff boundary and record the exact next operator step.

# Notes

- Use `docs/QUICKSTART.md` as the operator reference for the expected CLI flow.
- The objective is to verify the RP adapter path, not to ship a feature.
- If implementation reaches an auto-capable path, it should remain a no-op with respect to product code and only summarize what was validated.

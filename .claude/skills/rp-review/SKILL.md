# rp-review

Use this skill to run the AIWF review workflow for an existing implementation run.

## Steps

1. Confirm the target run already exists under `.ai/runs/<run_id>/` and is in `needs_review`.
2. Run:

   ```bash
   uv run aiwf run review --run-id <run_id>
   ```

3. Report the `run_id` and resulting status.
4. Point the user to the review artifacts that now exist for that run:
   - `.ai/runs/<run_id>/review-report.json`
   - `.ai/runs/<run_id>/claude-review-prompt.md` when manual Claude mode stops for handoff
5. If the run stops in `blocked` after writing the manual review handoff, finalize with:

   ```bash
   uv run aiwf resume <run_id>
   ```

## Notes

- `run review` is run-centric: it reviews an existing implement run and its artifacts rather than starting from a task file.
- `work-receipt.json` is only guaranteed after the review workflow reaches a terminal state.
- This skill is for review only; use `rp-plan` or `rp-implement` for earlier stages.
- `--auto` requires the `claude` CLI binary to be installed and available on `PATH`.

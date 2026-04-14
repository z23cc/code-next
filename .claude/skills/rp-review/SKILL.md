# rp-review

Use this skill to run the AIWF review workflow for a task file.

## Steps

1. Confirm the task path exists under `.ai/tasks/`.
2. Run:

   ```bash
   aiwf run review --task <task-path> --adapter claude
   ```

3. Report the `run_id`.
4. Point the user to:
   - `.ai/runs/<run_id>/review-report.json`
   - `.ai/runs/<run_id>/work-receipt.json`

## Notes

- Add `--auto` only when Claude CLI subprocess mode is intended.
- This skill is for review only; use `rp-plan` or `rp-implement` for earlier stages.
- `--auto` requires the `claude` CLI binary to be installed and available on `PATH`.

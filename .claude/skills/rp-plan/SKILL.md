# rp-plan

Use this skill to run the AIWF planning workflow for a task file.

## Steps

1. Confirm the task path exists under `.ai/tasks/`.
2. Run:

   ```bash
   uv run aiwf run plan --task <task-path> --adapter claude
   ```

3. Report the `run_id`.
4. Point the user to:
   - `.ai/runs/<run_id>/context-pack.md`
   - `.ai/runs/<run_id>/exec-plan.md`

## Notes

- Use `--adapter stub` only for tests or local debugging.
- Add `--auto` only when Claude CLI subprocess mode is explicitly desired.
- `--auto` requires the `claude` CLI binary to be installed and available on `PATH`.

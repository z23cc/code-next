# rp-implement

Use this skill to run the AIWF implementation workflow for a task file.

## Steps

1. Confirm the task path exists under `.ai/tasks/`.
2. Run:

   ```bash
   uv run aiwf run implement --task <task-path> --adapter claude
   ```

3. Report the `run_id` and current status.
4. In manual Claude mode, treat the first stop as an implementation handoff boundary:
   - inspect `.ai/runs/<run_id>/claude-implement-prompt.md`
   - complete the requested implementation work
   - resume the run with:

   ```bash
   uv run aiwf resume <run_id>
   ```

5. If the resumed run stops in `needs_review`, start the explicit review step with:

   ```bash
   uv run aiwf run review --run-id <run_id>
   ```

6. If manual review also stops for handoff, finalize with:

   ```bash
   uv run aiwf resume <run_id>
   ```

## Notes

- In manual Claude mode, prompt files are handoff artifacts, not proof that implement/review fully completed.
- Gates remain deterministic and run through the AIWF engine.
- `work-receipt.json` is a terminal artifact and may not exist yet while a run is `blocked` or `needs_review`.
- `--auto` requires the `claude` CLI binary to be installed and available on `PATH`.

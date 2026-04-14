# rp-implement

Use this skill to run the AIWF implementation workflow for a task file.

## Steps

1. Confirm the task path exists under `.ai/tasks/`.
2. Run:

   ```bash
   aiwf run implement --task <task-path> --adapter claude
   ```

3. Report the `run_id` and final status.
4. If the run fails during gates, suggest:

   ```bash
   aiwf resume <run_id> --adapter claude
   ```

## Notes

- In manual Claude mode, prompt files may be generated inside `.ai/runs/<run_id>/`.
- Gates remain deterministic and run through the AIWF engine.
- `--auto` requires the `claude` CLI binary to be installed and available on `PATH`.

"""Workflow orchestration for the aiwf kernel."""

from __future__ import annotations

from pathlib import Path

from aiwf.adapters.base import RunnerAdapter
from aiwf.artifacts import ArtifactStore
from aiwf.exceptions import StateError
from aiwf.gates import run_gates
from aiwf.loader import load_gate_set, load_policy, load_runbook, load_task
from aiwf.models import RunMeta, RunStatus, StageResult, TaskSpec, WorkReceipt
from aiwf.state import RunStateManager


class WorkflowEngine:
    """Coordinate task loading, adapter execution, state, and artifacts."""

    def __init__(
        self,
        adapter: RunnerAdapter,
        *,
        ai_root: str | Path = ".ai",
        repo_root: str | Path | None = None,
        state_manager: RunStateManager | None = None,
        adapter_name: str = "stub",
        adapter_auto: bool = False,
    ) -> None:
        self.adapter = adapter
        self.ai_root = Path(ai_root)
        self.repo_root = Path(repo_root) if repo_root is not None else self.ai_root.parent
        self.state_manager = state_manager or RunStateManager(self.ai_root)
        self.adapter_name = adapter_name
        self.adapter_auto = adapter_auto

    def run_plan(self, task_path: str | Path) -> str:
        """Run the stub-backed plan workflow."""
        task_file = Path(task_path)
        task = load_task(task_file)
        self._load_supporting_specs(task)
        run_id = self.state_manager.init_run(task, task_path=task_file)
        run_dir = self._run_dir(run_id)
        store = ArtifactStore(run_dir, state_manager=self.state_manager)
        self.state_manager.update_run(run_id, data=self._workflow_data("plan"))

        try:
            self.state_manager.transition(run_id, RunStatus.running, stage="discover")
            context = self.adapter.discover(task, run_dir)
            store.write_context_pack(context)
            self.state_manager.update_run(run_id, last_completed_stage="discover", data=self._workflow_data("plan"))

            plan_content = self.adapter.plan(task, context)
            store.write_exec_plan(plan_content)
            self.state_manager.update_run(run_id, last_completed_stage="plan", data=self._workflow_data("plan"))

            self._write_receipt(
                store,
                run_id,
                RunStatus.passed,
                "Plan workflow completed successfully.",
                ["context-pack.md", "exec-plan.md", "work-receipt.json"],
            )
            self.state_manager.transition(run_id, RunStatus.passed, stage="plan")
            return run_id
        except Exception as exc:
            self._handle_run_failure(run_id, store, "plan", exc)
            raise

    def run_implement(self, task_path: str | Path) -> str:
        """Run the stub-backed implement workflow."""
        task_file = Path(task_path)
        task = load_task(task_file)
        self._load_supporting_specs(task)
        run_id = self.state_manager.init_run(task, task_path=task_file)
        run_dir = self._run_dir(run_id)
        store = ArtifactStore(run_dir, state_manager=self.state_manager)
        self.state_manager.update_run(run_id, data=self._workflow_data("implement"))

        try:
            self._resume_implement(task, run_id, run_dir, store, start_after_stage=None)
            return run_id
        except Exception as exc:
            self._handle_run_failure(run_id, store, "implement", exc)
            raise

    def run_review(self, task_path: str | Path) -> str:
        """Run the stub-backed review workflow."""
        task_file = Path(task_path)
        task = load_task(task_file)
        self._load_supporting_specs(task)
        run_id = self.state_manager.init_run(task, task_path=task_file)
        run_dir = self._run_dir(run_id)
        store = ArtifactStore(run_dir, state_manager=self.state_manager)
        self.state_manager.update_run(run_id, data=self._workflow_data("review"))

        try:
            self.state_manager.transition(run_id, RunStatus.running, stage="review")
            review_report = self.adapter.review(task, run_dir)
            store.write_review_report(review_report)
            self.state_manager.update_run(run_id, last_completed_stage="review", data=self._workflow_data("review"))
            self._write_receipt(
                store,
                run_id,
                RunStatus.passed,
                "Review workflow completed successfully.",
                ["review-report.json", "work-receipt.json"],
            )
            self.state_manager.transition(run_id, RunStatus.passed, stage="review")
            return run_id
        except Exception as exc:
            self._handle_run_failure(run_id, store, "review", exc)
            raise

    def resume(self, run_id: str) -> str:
        """Resume a failed, blocked, or needs-review workflow run."""
        meta = self.state_manager.load_run(run_id)
        workflow = str(meta.data.get("workflow", "")).strip()
        if workflow not in {"plan", "implement", "review"}:
            raise StateError("Run does not include a resumable workflow mode", path=meta.run_dir, stage="resume")
        if meta.status not in {RunStatus.failed, RunStatus.blocked, RunStatus.needs_review}:
            raise StateError(
                f"Run in status {meta.status.value} cannot be resumed",
                path=meta.run_dir,
                stage="resume",
            )

        task = self._load_task_from_meta(meta)
        self._load_supporting_specs(task)
        run_dir = Path(meta.run_dir)
        store = ArtifactStore(run_dir, state_manager=self.state_manager)
        self.state_manager.transition(run_id, RunStatus.running, stage="resume", data={"workflow": workflow})

        try:
            if workflow == "plan":
                self._resume_plan(task, run_id, run_dir, store, meta.last_completed_stage)
            elif workflow == "implement":
                self._resume_implement(task, run_id, run_dir, store, meta.last_completed_stage)
            else:
                self._resume_review(task, run_id, run_dir, store, meta.last_completed_stage)
            return run_id
        except Exception as exc:
            self._handle_run_failure(run_id, store, workflow, exc)
            raise

    def _resume_plan(
        self,
        task: TaskSpec,
        run_id: str,
        run_dir: Path,
        store: ArtifactStore,
        last_completed_stage: str | None,
    ) -> None:
        if last_completed_stage is None:
            context = self.adapter.discover(task, run_dir)
            store.write_context_pack(context)
            self.state_manager.update_run(run_id, last_completed_stage="discover", data=self._workflow_data("plan"))
        else:
            context = str(store.read_artifact("context-pack.md"))

        if last_completed_stage != "plan":
            plan_content = self.adapter.plan(task, context)
            store.write_exec_plan(plan_content)
            self.state_manager.update_run(run_id, last_completed_stage="plan", data=self._workflow_data("plan"))

        self._write_receipt(
            store,
            run_id,
            RunStatus.passed,
            "Plan workflow completed successfully.",
            ["context-pack.md", "exec-plan.md", "work-receipt.json"],
        )
        self.state_manager.transition(run_id, RunStatus.passed, stage="plan")

    def _resume_implement(
        self,
        task: TaskSpec,
        run_id: str,
        run_dir: Path,
        store: ArtifactStore,
        start_after_stage: str | None,
    ) -> None:
        context: str
        plan_content: str

        if start_after_stage is None:
            self.state_manager.transition(run_id, RunStatus.running, stage="discover")
            context = self.adapter.discover(task, run_dir)
            store.write_context_pack(context)
            self.state_manager.update_run(run_id, last_completed_stage="discover", data=self._workflow_data("implement"))
            start_after_stage = "discover"
        else:
            context = str(store.read_artifact("context-pack.md"))

        if start_after_stage == "discover":
            plan_content = self.adapter.plan(task, context)
            store.write_exec_plan(plan_content)
            self.state_manager.update_run(run_id, last_completed_stage="plan", data=self._workflow_data("implement"))
            start_after_stage = "plan"
        else:
            plan_content = str(store.read_artifact("exec-plan.md"))

        if start_after_stage == "plan":
            result = self.adapter.execute(task, plan_content, run_dir)
            self._ensure_stage_passed(result)
            self.state_manager.update_run(run_id, last_completed_stage="implement", data=self._workflow_data("implement"))
            self.state_manager.transition(run_id, RunStatus.blocked, stage="implement")
            start_after_stage = "implement"

        if start_after_stage in {"implement", "gates"}:
            gate_set = load_gate_set(self.ai_root / "gates" / f"{task.gates}.yaml")
            report = run_gates(gate_set, self.repo_root)
            store.write_verify_report(report)
            self.state_manager.update_run(run_id, last_completed_stage="gates", data=self._workflow_data("implement"))

            if not report.passed:
                self._write_receipt(
                    store,
                    run_id,
                    RunStatus.failed,
                    "Implementation workflow failed during gates.",
                    ["context-pack.md", "exec-plan.md", "verify-report.json", "work-receipt.json"],
                    notes=["Gate verification failed."],
                )
                self.state_manager.transition(
                    run_id,
                    RunStatus.failed,
                    stage="gates",
                    error="Gate verification failed",
                )
                return

            self.state_manager.transition(run_id, RunStatus.needs_review, stage="gates")
            start_after_stage = "gates"

        if start_after_stage == "gates":
            review_report = self.adapter.review(task, run_dir)
            store.write_review_report(review_report)
            self.state_manager.update_run(run_id, last_completed_stage="review", data=self._workflow_data("implement"))
            self._write_receipt(
                store,
                run_id,
                RunStatus.passed,
                "Implementation workflow completed successfully.",
                [
                    "context-pack.md",
                    "exec-plan.md",
                    "verify-report.json",
                    "review-report.json",
                    "work-receipt.json",
                ],
            )
            self.state_manager.transition(run_id, RunStatus.passed, stage="review")

    def _resume_review(
        self,
        task: TaskSpec,
        run_id: str,
        run_dir: Path,
        store: ArtifactStore,
        last_completed_stage: str | None,
    ) -> None:
        if last_completed_stage != "review":
            review_report = self.adapter.review(task, run_dir)
            store.write_review_report(review_report)
            self.state_manager.update_run(run_id, last_completed_stage="review", data=self._workflow_data("review"))

        self._write_receipt(
            store,
            run_id,
            RunStatus.passed,
            "Review workflow completed successfully.",
            ["review-report.json", "work-receipt.json"],
        )
        self.state_manager.transition(run_id, RunStatus.passed, stage="review")

    def _write_receipt(
        self,
        store: ArtifactStore,
        run_id: str,
        status: RunStatus,
        summary: str,
        artifacts: list[str],
        *,
        notes: list[str] | None = None,
    ) -> None:
        receipt = WorkReceipt(
            run_id=run_id,
            status=status,
            summary=summary,
            artifacts=artifacts,
            notes=notes or [],
        )
        store.write_work_receipt(receipt)

    def _handle_run_failure(
        self,
        run_id: str,
        store: ArtifactStore,
        workflow: str,
        exc: Exception,
    ) -> None:
        self._write_receipt(
            store,
            run_id,
            RunStatus.failed,
            f"{workflow.capitalize()} workflow failed: {exc}",
            ["work-receipt.json"],
            notes=[str(exc)],
        )
        meta = self.state_manager.load_run(run_id)
        if meta.status is RunStatus.failed:
            self.state_manager.update_run(run_id, error=str(exc), data=self._workflow_data(workflow))
        else:
            self.state_manager.transition(run_id, RunStatus.failed, stage=workflow, error=str(exc))

    def _workflow_data(self, workflow: str) -> dict[str, object]:
        return {
            "workflow": workflow,
            "adapter": self.adapter_name,
            "auto": self.adapter_auto,
        }

    def _load_supporting_specs(self, task: TaskSpec) -> None:
        load_runbook(self.ai_root / "runbooks" / f"{task.runbook}.md")
        load_policy(self.ai_root / "policies" / f"{task.policy}.md")

    def _load_task_from_meta(self, meta: RunMeta) -> TaskSpec:
        if not meta.task_path:
            raise StateError("Run does not include an original task path", path=meta.run_dir, stage="resume")
        return load_task(meta.task_path)

    def _ensure_stage_passed(self, result: StageResult) -> None:
        if result.status is not RunStatus.passed:
            raise StateError(
                f"Stage {result.stage} did not pass",
                stage=result.stage,
            )

    def _run_dir(self, run_id: str) -> Path:
        return self.ai_root / "runs" / run_id

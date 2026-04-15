"""Workflow orchestration for the aiwf kernel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aiwf.adapters import restore_host_contract
from aiwf.adapters.base import HostContract, RunnerAdapter
from aiwf.artifacts import ArtifactStore
from aiwf.exceptions import ArtifactError, StateError
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
        host_contract: HostContract | None = None,
        adapter_resolver: Callable[[HostContract], RunnerAdapter] | None = None,
    ) -> None:
        self.adapter = adapter
        self.ai_root = Path(ai_root)
        self.repo_root = Path(repo_root) if repo_root is not None else self.ai_root.parent
        self.state_manager = state_manager or RunStateManager(self.ai_root)
        self.host_contract = host_contract or adapter.host_contract
        self.adapter_resolver = adapter_resolver
        if self.adapter.host_contract != self.host_contract:
            raise ValueError("Configured adapter does not match the provided host contract")

    @property
    def adapter_name(self) -> str:
        return self.host_contract.adapter

    @property
    def adapter_auto(self) -> bool:
        return self.host_contract.auto

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

    def run_review(self, run_id: str) -> str:
        """Run review against an existing implementation run and its artifacts."""
        meta = self.state_manager.load_run(run_id)
        workflow = str(meta.data.get("workflow", "")).strip()
        if workflow != "implement":
            raise StateError("Review requires an existing implementation run", path=meta.run_dir, stage="review")
        if meta.status is not RunStatus.needs_review:
            raise StateError(
                f"Run in status {meta.status.value} is not ready for review",
                path=meta.run_dir,
                stage="review",
            )
        if meta.last_completed_stage not in {"gates", "review"}:
            raise StateError("Run has not reached the review boundary", path=meta.run_dir, stage="review")

        self._restore_execution_metadata(meta, stage="review")
        task = self._load_task_from_meta(meta)
        self._load_supporting_specs(task)
        run_dir = Path(meta.run_dir)
        store = ArtifactStore(run_dir, state_manager=self.state_manager)
        self._require_review_artifacts(store)

        try:
            self.state_manager.transition(run_id, RunStatus.running, stage="review", data=self._workflow_data(workflow))
            self._resume_review(
                task,
                run_id,
                run_dir,
                store,
                meta.last_completed_stage,
                workflow_name=workflow,
                success_summary="Review workflow completed successfully.",
                success_artifacts=["review-report.json", "work-receipt.json"],
            )
            return run_id
        except Exception as exc:
            self._handle_run_failure(run_id, store, workflow, exc)
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

        self._restore_execution_metadata(meta, stage="resume")
        task = self._load_task_from_meta(meta)
        self._load_supporting_specs(task)
        run_dir = Path(meta.run_dir)
        store = ArtifactStore(run_dir, state_manager=self.state_manager)
        self.state_manager.transition(run_id, RunStatus.running, stage="resume", data=self._workflow_data(workflow))

        try:
            if workflow == "plan":
                self._resume_plan(task, run_id, run_dir, store, meta.last_completed_stage)
            elif workflow == "implement":
                self._resume_implement(task, run_id, run_dir, store, meta.last_completed_stage)
            else:
                self._resume_review(
                    task,
                    run_id,
                    run_dir,
                    store,
                    meta.last_completed_stage,
                    workflow_name=workflow,
                    success_summary="Review workflow completed successfully.",
                    success_artifacts=["review-report.json", "work-receipt.json"],
                )
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
            self.state_manager.update_run(run_id, last_completed_stage="implement", data=self._workflow_data("implement"))
            if result.status is RunStatus.blocked:
                self.state_manager.transition(run_id, RunStatus.blocked, stage="implement")
                return
            self._ensure_stage_passed(result)
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
            if self._requires_explicit_review_handoff():
                return
            start_after_stage = "gates"

        if start_after_stage in {"gates", "review"}:
            self._resume_review(
                task,
                run_id,
                run_dir,
                store,
                start_after_stage,
                workflow_name="implement",
                success_summary="Implementation workflow completed successfully.",
                success_artifacts=[
                    "context-pack.md",
                    "exec-plan.md",
                    "verify-report.json",
                    "review-report.json",
                    "work-receipt.json",
                ],
            )

    def _resume_review(
        self,
        task: TaskSpec,
        run_id: str,
        run_dir: Path,
        store: ArtifactStore,
        last_completed_stage: str | None,
        *,
        workflow_name: str,
        success_summary: str,
        success_artifacts: list[str],
    ) -> None:
        self._require_review_artifacts(store)
        review_report: dict[str, object]
        if last_completed_stage != "review":
            review_report = self.adapter.review(task, run_dir)
            self._validate_review_report(review_report, run_dir)
            store.write_review_report(review_report)
            self.state_manager.update_run(run_id, last_completed_stage="review", data=self._workflow_data(workflow_name))
            if self._requires_explicit_review_handoff(review_report):
                self.state_manager.transition(run_id, RunStatus.blocked, stage="review")
                return
        else:
            stored_review_report = store.read_artifact("review-report.json")
            if not isinstance(stored_review_report, dict):
                raise StateError("Stored review-report.json must be a JSON object", path=run_dir / "review-report.json", stage="review")
            review_report = stored_review_report
            self._validate_review_report(review_report, run_dir)

        self._write_receipt(
            store,
            run_id,
            RunStatus.passed,
            success_summary,
            success_artifacts,
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
            "host_contract": self.host_contract.to_metadata(),
        }

    def _restore_execution_metadata(self, meta: RunMeta, *, stage: str) -> None:
        try:
            contract = restore_host_contract(meta.data)
        except ValueError as exc:
            raise StateError("Run does not include a valid stored host contract", path=meta.run_dir, stage=stage) from exc

        self.host_contract = contract
        if self.adapter.host_contract == contract:
            return
        if self.adapter_resolver is None:
            raise StateError("WorkflowEngine adapter does not match stored host contract", path=meta.run_dir, stage=stage)
        try:
            restored_adapter = self.adapter_resolver(contract)
        except Exception as exc:
            raise StateError("Failed to restore adapter from stored host contract", path=meta.run_dir, stage=stage) from exc
        if restored_adapter.host_contract != contract:
            raise StateError("Restored adapter does not honor stored host contract", path=meta.run_dir, stage=stage)
        self.adapter = restored_adapter

    def _require_review_artifacts(self, store: ArtifactStore) -> None:
        for artifact_name in self.host_contract.review.required_run_artifacts:
            try:
                store.read_artifact(artifact_name)
            except ArtifactError as exc:
                raise StateError(
                    f"Run is missing required review artifact {artifact_name!r}",
                    path=store.run_dir / artifact_name,
                    stage="review",
                ) from exc

    def _requires_explicit_review_handoff(self, review_report: dict[str, object] | None = None) -> bool:
        expected = self.host_contract.capabilities.requires_explicit_review_handoff
        if review_report is None:
            return expected
        reported_mode = str(review_report.get("mode", "")).strip()
        if reported_mode in {"manual", "auto"} and (reported_mode == "manual") != expected:
            raise StateError(
                f"Review report mode {reported_mode!r} does not match stored host contract "
                f"(requires_explicit_review_handoff={expected})",
                stage="review",
            )
        return expected

    def _validate_review_report(self, review_report: dict[str, object], run_dir: Path) -> None:
        review_contract = self.host_contract.review

        for field_name in review_contract.required_report_string_fields:
            value = review_report.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise StateError(
                    f"Review report is missing required string field {field_name!r}",
                    path=run_dir / "review-report.json",
                    stage="review",
                )

        for field_name in review_contract.required_report_list_fields:
            value = review_report.get(field_name)
            if not isinstance(value, list):
                raise StateError(
                    f"Review report field {field_name!r} must be a list",
                    path=run_dir / "review-report.json",
                    stage="review",
                )

        expected_mode = review_contract.expected_report_mode
        if expected_mode is not None:
            reported_mode = review_report.get("mode")
            if reported_mode != expected_mode:
                raise StateError(
                    f"Review report mode {reported_mode!r} does not match expected review evidence mode {expected_mode!r}",
                    path=run_dir / "review-report.json",
                    stage="review",
                )

        linked_field = review_contract.linked_report_artifact_field
        if linked_field is None:
            return
        artifact_name = review_report.get(linked_field)
        if not isinstance(artifact_name, str) or not artifact_name.strip():
            raise StateError(
                f"Review report is missing linked artifact field {linked_field!r}",
                path=run_dir / "review-report.json",
                stage="review",
            )
        linked_artifact_path = run_dir / artifact_name
        if not linked_artifact_path.exists() or not linked_artifact_path.is_file():
            raise StateError(
                f"Review evidence artifact {artifact_name!r} referenced by {linked_field!r} does not exist",
                path=linked_artifact_path,
                stage="review",
            )

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

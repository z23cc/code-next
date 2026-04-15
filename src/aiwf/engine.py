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
from aiwf.models import (
    EventRecord,
    RunArtifactRef,
    RunDiagnostics,
    RunGateEvidence,
    RunHostDiagnostics,
    RunMeta,
    RunProvenance,
    RunProvenanceArtifact,
    RunReviewEvidence,
    RunStatus,
    RunTimelineEntry,
    StageResult,
    TaskSpec,
    WorkReceipt,
)
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
            self._write_runtime_surfaces(store, workflow="plan")
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
            self._write_runtime_surfaces(store, workflow="implement")
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
            self._write_runtime_surfaces(store, workflow=workflow)
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
            self._write_runtime_surfaces(store, workflow=workflow)
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
            self._record_stage_result(run_id, result)
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
        try:
            self._write_runtime_surfaces(store, workflow=workflow)
        except Exception:
            pass

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

    def _record_stage_result(self, run_id: str, result: StageResult) -> None:
        self.state_manager.append_event(
            run_id,
            EventRecord(
                event="stage_result_recorded",
                status=result.status,
                stage=result.stage,
                data={
                    "summary": result.summary,
                    "outputs": list(result.outputs),
                    "metadata": dict(result.metadata),
                },
            ),
        )

    def _write_runtime_surfaces(self, store: ArtifactStore, *, workflow: str) -> None:
        diagnostics = self._build_run_diagnostics(store.run_id, store.run_dir, workflow=workflow)
        store.write_run_diagnostics(diagnostics)
        provenance = self._build_run_provenance(store, workflow=workflow, diagnostics=diagnostics)
        store.write_run_provenance(provenance)

    def _build_run_diagnostics(self, run_id: str, run_dir: Path, *, workflow: str) -> RunDiagnostics:
        meta = self.state_manager.load_run(run_id)
        events = self.state_manager.load_events(run_id)
        key_artifacts = self._collect_key_artifacts(run_dir)
        artifact_names = {artifact.name for artifact in key_artifacts}

        return RunDiagnostics(
            run_id=run_id,
            workflow=workflow,
            status=meta.status,
            last_completed_stage=meta.last_completed_stage,
            status_reason=self._diagnostics_status_reason(meta, artifact_names, run_dir),
            resumable=meta.status in {RunStatus.blocked, RunStatus.failed},
            reviewable=meta.status is RunStatus.needs_review,
            resume_command=f"uv run aiwf resume {run_id}" if meta.status in {RunStatus.blocked, RunStatus.failed} else None,
            review_command=f"uv run aiwf run review --run-id {run_id}" if meta.status is RunStatus.needs_review else None,
            next_actions=self._diagnostics_next_actions(meta, artifact_names, run_id, run_dir),
            error=meta.error,
            host=RunHostDiagnostics(
                adapter=self.host_contract.adapter,
                mode=self.host_contract.mode,
                supports_auto_execution=self.host_contract.capabilities.supports_auto_execution,
                requires_explicit_review_handoff=self.host_contract.capabilities.requires_explicit_review_handoff,
            ),
            key_artifacts=key_artifacts,
            stage_timeline=self._build_stage_timeline(events),
        )

    def _build_run_provenance(
        self,
        store: ArtifactStore,
        *,
        workflow: str,
        diagnostics: RunDiagnostics,
    ) -> RunProvenance:
        meta = self.state_manager.load_run(store.run_id)
        events = self.state_manager.load_events(store.run_id)
        artifact_refs = self._collect_artifact_refs(store.run_dir)
        artifact_index: dict[str, RunProvenanceArtifact] = {}

        def add_artifact(
            name: str,
            *,
            stage: str | None,
            category: str,
            related_artifacts: list[str] | None = None,
        ) -> None:
            artifact = artifact_refs.get(name)
            if artifact is None:
                return
            artifact_index[name] = RunProvenanceArtifact(
                name=artifact.name,
                path=artifact.path,
                stage=stage,
                category=category,
                related_artifacts=sorted(set(related_artifacts or [])),
            )

        add_artifact("context-pack.md", stage="discover", category="context")
        add_artifact("exec-plan.md", stage="plan", category="plan")
        add_artifact("verify-report.json", stage="gates", category="gate_report")
        add_artifact("work-receipt.json", stage=None, category="receipt")
        add_artifact("run-diagnostics.json", stage=None, category="diagnostics")

        implement_output_names = self._implement_output_artifact_names(events, artifact_refs)
        for artifact_name in implement_output_names:
            category = "handoff" if "prompt" in artifact_name else "stage_output"
            add_artifact(artifact_name, stage="implement", category=category)

        review_report = self._read_json_artifact_if_present(store, "review-report.json")
        linked_review_artifact_names = self._linked_review_artifact_names(review_report)
        add_artifact(
            "review-report.json",
            stage="review",
            category="review_report",
            related_artifacts=[
                *linked_review_artifact_names,
                *[
                    artifact_name
                    for artifact_name in self.host_contract.review.required_run_artifacts
                    if artifact_name in artifact_refs
                ],
            ],
        )
        for artifact_name in linked_review_artifact_names:
            category = "handoff" if "prompt" in artifact_name else "review_evidence"
            add_artifact(
                artifact_name,
                stage="review",
                category=category,
                related_artifacts=["review-report.json"],
            )

        verify_report = self._read_json_artifact_if_present(store, "verify-report.json")
        gate_report_ref = artifact_refs.get("verify-report.json")
        review_required_artifact_names = list(self.host_contract.review.required_run_artifacts)
        available_review_required_artifacts = [
            artifact_refs[artifact_name]
            for artifact_name in review_required_artifact_names
            if artifact_name in artifact_refs
        ]

        gate_evidence = RunGateEvidence(
            report=gate_report_ref,
            gate_set=self._json_string_value(verify_report, "gate_set"),
            passed=self._json_bool_value(verify_report, "passed"),
        )
        review_evidence = RunReviewEvidence(
            report=artifact_refs.get("review-report.json"),
            mode=self._json_string_value(review_report, "mode"),
            linked_report_artifact_field=self.host_contract.review.linked_report_artifact_field,
            linked_artifacts=[
                artifact_refs[artifact_name]
                for artifact_name in linked_review_artifact_names
                if artifact_name in artifact_refs
            ],
            required_run_artifacts=review_required_artifact_names,
            available_required_artifacts=available_review_required_artifacts,
        )

        return RunProvenance(
            run_id=store.run_id,
            workflow=workflow,
            status=meta.status,
            last_completed_stage=meta.last_completed_stage,
            host=diagnostics.host,
            artifact_index=sorted(
                artifact_index.values(),
                key=lambda artifact: (
                    artifact.stage or "",
                    artifact.category,
                    artifact.name,
                ),
            ),
            gate_evidence=gate_evidence,
            review_evidence=review_evidence,
        )

    def _build_stage_timeline(self, events: list[EventRecord]) -> list[RunTimelineEntry]:
        return [
            RunTimelineEntry(
                ts=event.ts,
                event=event.event,
                stage=event.stage,
                status=event.status,
            )
            for event in events
            if event.event in {"run_initialized", "run_updated", "status_transition"}
        ]

    def _collect_key_artifacts(self, run_dir: Path) -> list[RunArtifactRef]:
        return [
            RunArtifactRef(name=path.name, path=str(path))
            for path in sorted(run_dir.iterdir())
            if path.is_file() and path.name not in {"run.json", "events.ndjson", "run-diagnostics.json", "run-provenance.json"}
        ]

    def _collect_artifact_refs(self, run_dir: Path) -> dict[str, RunArtifactRef]:
        return {
            path.name: RunArtifactRef(name=path.name, path=str(path))
            for path in sorted(run_dir.iterdir())
            if path.is_file() and path.name not in {"run.json", "events.ndjson", "run-provenance.json"}
        }

    def _implement_output_artifact_names(
        self,
        events: list[EventRecord],
        artifact_refs: dict[str, RunArtifactRef],
    ) -> list[str]:
        for event in reversed(events):
            if event.event != "stage_result_recorded" or event.stage != "implement":
                continue
            outputs = event.data.get("outputs")
            if not isinstance(outputs, list):
                continue
            return sorted(
                output_name
                for output_name in outputs
                if isinstance(output_name, str) and output_name in artifact_refs
            )
        return self._matching_artifact_names(set(artifact_refs), stage="implement")

    def _read_json_artifact_if_present(self, store: ArtifactStore, name: str) -> dict[str, object] | None:
        artifact_path = store.run_dir / name
        if not artifact_path.exists():
            return None
        artifact = store.read_artifact(name)
        return artifact if isinstance(artifact, dict) else None

    def _linked_review_artifact_names(self, review_report: dict[str, object] | None) -> list[str]:
        linked_field = self.host_contract.review.linked_report_artifact_field
        if review_report is None or linked_field is None:
            return []
        artifact_name = review_report.get(linked_field)
        if not isinstance(artifact_name, str) or not artifact_name.strip():
            return []
        return [artifact_name.strip()]

    def _json_string_value(self, payload: dict[str, object] | None, key: str) -> str | None:
        if payload is None:
            return None
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _json_bool_value(self, payload: dict[str, object] | None, key: str) -> bool | None:
        if payload is None:
            return None
        value = payload.get(key)
        return value if isinstance(value, bool) else None

    def _diagnostics_status_reason(self, meta: RunMeta, artifact_names: set[str], run_dir: Path) -> str:
        if meta.status is RunStatus.passed:
            return "Run completed successfully."
        if meta.status is RunStatus.failed:
            if meta.last_completed_stage == "gates" and "verify-report.json" in artifact_names:
                return "Run failed during gates and requires fixes before resume."
            return meta.error or "Run failed and requires operator action before resume."
        if meta.status is RunStatus.needs_review:
            return "Implementation completed verification and is waiting for an explicit review step."
        if meta.status is RunStatus.blocked:
            if meta.last_completed_stage == "implement":
                implement_handoff = self._matching_artifact_names(artifact_names, stage="implement")
                if implement_handoff:
                    return f"Run is blocked at implement waiting for operator action on {', '.join(implement_handoff)}."
                return "Run is blocked at implement waiting for operator action."
            if meta.last_completed_stage == "review":
                review_handoff = self._linked_review_artifact_name(run_dir)
                if review_handoff:
                    return f"Run is blocked at review waiting for operator action on {review_handoff}."
                return "Run is blocked at review waiting for operator action."
            return "Run is blocked and requires operator action before it can continue."
        if meta.status is RunStatus.running:
            return "Run is currently executing."
        if meta.status is RunStatus.canceled:
            return "Run has been canceled."
        return "Run is queued and has not started yet."

    def _diagnostics_next_actions(
        self,
        meta: RunMeta,
        artifact_names: set[str],
        run_id: str,
        run_dir: Path,
    ) -> list[str]:
        if meta.status is RunStatus.needs_review:
            actions = ["Inspect verify-report.json and implementation artifacts before review."]
            actions.append(f"Run `uv run aiwf run review --run-id {run_id}` to start review.")
            return actions
        if meta.status is RunStatus.blocked:
            if meta.last_completed_stage == "implement":
                handoff_artifacts = self._matching_artifact_names(artifact_names, stage="implement")
                if handoff_artifacts:
                    return [
                        f"Inspect {', '.join(handoff_artifacts)} to complete the external implementation handoff.",
                        f"Run `uv run aiwf resume {run_id}` when the implementation handoff is complete.",
                    ]
                return [f"Run `uv run aiwf resume {run_id}` when the blocked implementation step is complete."]
            if meta.last_completed_stage == "review":
                review_handoff = self._linked_review_artifact_name(run_dir)
                if review_handoff:
                    return [
                        f"Inspect {review_handoff} to complete the review handoff.",
                        f"Run `uv run aiwf resume {run_id}` when review is complete.",
                    ]
                return [f"Run `uv run aiwf resume {run_id}` when the blocked review step is complete."]
            return [f"Run `uv run aiwf resume {run_id}` after addressing the blocking issue."]
        if meta.status is RunStatus.failed:
            if meta.last_completed_stage == "gates" and "verify-report.json" in artifact_names:
                return [
                    "Inspect verify-report.json for failing gate details.",
                    f"Run `uv run aiwf resume {run_id}` after fixing the reported problems.",
                ]
            return [
                "Inspect work-receipt.json and the latest stage artifacts for failure details.",
                f"Run `uv run aiwf resume {run_id}` after addressing the failure.",
            ]
        return []

    def _matching_artifact_names(self, artifact_names: set[str], *, stage: str) -> list[str]:
        return sorted(
            artifact_name
            for artifact_name in artifact_names
            if stage in artifact_name and ("prompt" in artifact_name or "response" in artifact_name)
        )

    def _linked_review_artifact_name(self, run_dir: Path) -> str | None:
        linked_field = self.host_contract.review.linked_report_artifact_field
        if linked_field is None:
            return None
        review_report_path = run_dir / "review-report.json"
        if not review_report_path.exists():
            return None
        try:
            report = ArtifactStore(run_dir, state_manager=self.state_manager).read_artifact("review-report.json")
        except ArtifactError:
            return None
        if not isinstance(report, dict):
            return None
        artifact_name = report.get(linked_field)
        return artifact_name.strip() if isinstance(artifact_name, str) and artifact_name.strip() else None

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

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aiwf.models import (
    GateSet,
    RpBridgeAgentTranscriptArtifactContent,
    RpBridgeResolvedIdentity,
    RpBridgeRunConfig,
    RpBridgeSeedingArtifactContent,
    RunMeta,
    RunStatus,
    RunbookSpec,
    TaskSpec,
)


def test_task_spec_populates_slug_and_defaults() -> None:
    task = TaskSpec(title="Implement Milestone One", body="Finish the M1 scaffold.")

    assert task.slug == "implement-milestone-one"
    assert task.runbook == "default"
    assert task.gates == "default"
    assert task.policy == "repo-policy"


def test_runbook_and_gate_models_validate_nested_data() -> None:
    runbook = RunbookSpec(
        name="default",
        stages=[
            {
                "name": "discover",
                "outputs": ["context-pack.md"],
                "required": True,
                "retry_limit": 0,
                "pause_on": ["blocked"],
            }
        ],
        body="Use the default workflow.",
    )
    gate_set = GateSet(gates=[{"name": "lint", "command": "ruff check src/ tests/"}])

    assert runbook.stages[0].name == "discover"
    assert runbook.stages[0].outputs == ["context-pack.md"]
    assert runbook.stages[0].required is True
    assert runbook.stages[0].retry_limit == 0
    assert runbook.stages[0].pause_on == ["blocked"]
    assert gate_set.gates[0].timeout_seconds == 120


def test_run_meta_uses_enum_status() -> None:
    meta = RunMeta(
        run_id="run-123",
        run_dir=".ai/runs/run-123",
        task_title="Example Task",
        task_slug="example-task",
        status=RunStatus.running,
    )

    assert meta.status is RunStatus.running


def test_task_spec_requires_title() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(body="Missing the required title field.")


def test_runbook_stage_strategy_fields_default_backward_compatibly() -> None:
    runbook = RunbookSpec(
        name="default",
        stages=[{"name": "review"}],
    )

    assert runbook.stages[0].required is True
    assert runbook.stages[0].retry_limit == 0
    assert runbook.stages[0].pause_on == []


def test_rp_bridge_run_config_round_trips() -> None:
    config = RpBridgeRunConfig(
        mode="manual-assist",
        workspace="workspace-alpha",
        tab="implement-tab",
        context_id="ctx-123",
        agent_role="implementer",
        timeout_seconds=900,
        export_transcript=True,
    )

    assert config.model_dump(mode="json") == {
        "mode": "manual-assist",
        "workspace": "workspace-alpha",
        "tab": "implement-tab",
        "context_id": "ctx-123",
        "agent_role": "implementer",
        "timeout_seconds": 900,
        "export_transcript": True,
        "resolved": None,
    }


def test_rp_bridge_run_config_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError, match="non-empty string"):
        RpBridgeRunConfig(mode="manual-assist", workspace="   ")

    with pytest.raises(ValidationError, match="timeout_seconds"):
        RpBridgeRunConfig(mode="manual-assist", timeout_seconds=0)


def test_rp_bridge_run_config_supports_resolved_identity() -> None:
    config = RpBridgeRunConfig(
        mode="managed-agent",
        workspace="workspace-alpha",
        resolved=RpBridgeResolvedIdentity(
            resolved_workspace_id="workspace-1",
            resolved_workspace_name="workspace-alpha",
            resolved_window_id=7,
            resolved_tab_id="tab-22",
            resolved_tab_name="implement-tab",
            resolved_context_id="ctx-999",
        ),
    )

    payload = config.model_dump(mode="json")
    assert payload["resolved"]["resolved_workspace_id"] == "workspace-1"
    assert payload["resolved"]["resolved_context_id"] == "ctx-999"


def test_rp_bridge_agent_transcript_artifact_content_validates() -> None:
    payload = RpBridgeAgentTranscriptArtifactContent.model_validate(
        {
            "version": 1,
            "session_id": "agent-session-1",
            "transcript": "# transcript",
            "events": [{"kind": "agent_wait", "status": "completed"}],
            "handoff_summary": "ready for review",
            "captured_at": "2026-04-17T01:00:00Z",
        }
    )

    assert payload.session_id == "agent-session-1"
    assert payload.handoff_summary == "ready for review"


def test_rp_bridge_seeding_artifact_content_validates() -> None:
    payload = RpBridgeSeedingArtifactContent.model_validate(
        {
            "version": 1,
            "mode": "manual-assist",
            "status": "seeded",
            "manual_handoff_required": True,
            "workspace": "workspace-alpha",
            "summary": "Seeded aiwf artifacts into RepoPrompt context.",
            "selected_artifacts": ["context-pack.md", "exec-plan.md"],
            "selected_paths": [".ai/runs/run-1/context-pack.md", ".ai/runs/run-1/exec-plan.md"],
            "attempted_tools": ["manage_selection", "workspace_context"],
            "calls": [
                {
                    "step": "manage_selection_add",
                    "tool": "manage_selection",
                    "ok": True,
                    "command": ["rp", "--manage-selection"],
                    "summary": "Seeded 2 aiwf artifact path(s) into RepoPrompt context",
                    "detail": {"selected_paths": [".ai/runs/run-1/context-pack.md"]},
                }
            ],
        }
    )

    assert payload.status == "seeded"
    assert payload.calls[0].tool == "manage_selection"


def test_runbook_stage_strategy_fields_reject_invalid_values() -> None:
    with pytest.raises(ValidationError, match="retry_limit"):
        RunbookSpec(name="default", stages=[{"name": "gates", "retry_limit": -1}])

    with pytest.raises(ValidationError, match="pause_on"):
        RunbookSpec(name="default", stages=[{"name": "implement", "pause_on": ["blocked", "blocked"]}])

    with pytest.raises(ValidationError, match="runbook stages must be unique"):
        RunbookSpec(
            name="default",
            stages=[
                {"name": "plan"},
                {"name": "plan"},
            ],
        )

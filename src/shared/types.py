"""Unified API response models for Hatchet workflows."""

from typing import TypedDict

from pydantic import BaseModel

from src.shared.enums import ResumeAction, ToolName, WorkflowStatus


class K8sDevOpsInput(BaseModel):
    task: str = "diagnose and fix cluster issues"
    source: str = ""


class K8sToolInput(BaseModel):
    tool: ToolName
    params: dict = {}


class K8sResumeInput(BaseModel):
    action: ResumeAction = ResumeAction.APPROVE
    thread_id: str = ""
    command_override: str = ""


class K8sAgentResult(BaseModel):
    """Unified response returned by k8s_agent workflows.

    All status paths populate the same core fields. ``proposed_fix`` and
    ``cluster_issues`` are set only when the graph paused for approval.
    """

    status: WorkflowStatus
    diagnosis: str = ""
    issues_found: int = 0
    failed_retries: int = 0
    fix_applied: str = ""
    fix_result: str = ""
    proposed_fix: str = ""
    cluster_issues: list[dict] = []
    thread_id: str = ""


class K8sState(TypedDict):
    cluster_issues: list[dict]
    diagnosis: str
    fix_failed: bool
    fix_result: str
    failed_retries: int
    proposed_fix: str
    rejected: bool
    task: str


def initial_state(task: str) -> K8sState:
    return {
        "cluster_issues": [],
        "diagnosis": "",
        "fix_failed": False,
        "fix_result": "",
        "failed_retries": 0,
        "proposed_fix": "",
        "rejected": False,
        "task": task,
    }

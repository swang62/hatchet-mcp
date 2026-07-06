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


class K8sAgentResult(TypedDict, total=False):
    """Normalized MCP tool output for k8s_agent and k8s_resume workflows."""

    status: WorkflowStatus
    diagnosis: str
    proposed_fix: str
    cluster_issues: list[dict]
    thread_id: str
    fix_result: str


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

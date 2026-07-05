"""Unified API response models for Hatchet workflows."""

from pydantic import BaseModel

from src.shared.enums import WorkflowStatus


class K8sAgentResult(BaseModel):
    """Unified response returned by k8s_check and k8s_resume workflows.

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

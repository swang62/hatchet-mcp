"""Scheduled operations: notifications and cron registration."""

import os

import httpx
from hatchet_sdk import Hatchet

from src.shared.constants import K8S_DEVOPS_WORKFLOW

NOTIFICATION_TIMEOUT = 10


def send_approval_notification(result: dict, thread_id: str) -> None:
    """Send a push notification about a fix awaiting human approval."""
    url = os.getenv("NOTIFICATION_URL", "")
    if not url:
        return
    diagnosis = result.get("diagnosis", "")
    issues = result.get("cluster_issues", [])
    proposed_fix = result.get("proposed_fix", "")
    issue_lines = "\n".join(
        f"- {i.get('namespace', '?')}/{i.get('name', '?')}: {i.get('reason', '?')}"
        for i in issues[:10]
    )
    body = (
        f"Diagnosis: {diagnosis}\n\n"
        f"Issues ({len(issues)}):\n{issue_lines}\n\n"
        f"Proposed fix: {proposed_fix}\n\n"
        f"Thread: {thread_id}\n"
        f"Use resume_devops_agent to approve or reject."
    )
    try:
        httpx.post(
            url,
            json={
                "title": f"K8s DevOps: {len(issues)} issue(s) found - approval needed",
                "message": body,
                "tags": ["warning", "kubernetes"],
                "priority": 4,
            },
            timeout=NOTIFICATION_TIMEOUT,
        )
    except Exception as e:
        print(f"Failed to send notification: {e}")


def register_nightly_cron(hatchet: Hatchet) -> None:
    """Register the nightly health check cron (idempotent)."""
    if not os.getenv("NOTIFICATION_URL"):
        return
    try:
        hatchet.cron.create(
            workflow_name=K8S_DEVOPS_WORKFLOW,
            cron_name="nightly_check",
            expression="0 10 * * *",
            input={"task": "routine nightly cluster health check", "source": "cron"},
            additional_metadata={"trigger": "cron", "cron_name": "nightly_check"},
        )
    except Exception:
        pass  # already registered or engine unavailable, non-fatal

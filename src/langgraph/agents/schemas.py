from typing import TypedDict


class K8sState(TypedDict):
    cluster_issues: list[dict]
    diagnosis: str
    fix_failed: bool
    fix_result: str
    proposed_fix: str
    rejected: bool
    retry_count: int
    task: str
    verified: bool


def initial_state(task: str) -> K8sState:
    return {
        "cluster_issues": [],
        "diagnosis": "",
        "fix_failed": False,
        "fix_result": "",
        "proposed_fix": "",
        "rejected": False,
        "retry_count": 0,
        "task": task,
        "verified": False,
    }

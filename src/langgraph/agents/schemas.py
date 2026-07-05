from typing import TypedDict


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

"""Hatchet workflow: K8s DevOps agent.

Triggered by the k8s:devops event.  Runs the full LangGraph graph and
relies on LangSmith tracing for per-node visibility.
"""

from hatchet_sdk import Context

from src.hatchet_worker.models import K8sDevOpsInput
from src.langgraph.agents.k8s_devops import K8sState
from src.langgraph.agents.k8s_devops import graph as k8s_graph


def run_k8s_check(input: K8sDevOpsInput, ctx: Context) -> dict:
    state: K8sState = {
        "task": input.task,
        "cluster_issues": [],
        "diagnosis": "",
        "proposed_fix": "",
        "fix_result": "",
        "verified": False,
        "retry_count": 0,
        "max_retries": 3,
        "decision": "",
    }

    result = k8s_graph.invoke(state)

    verified = result.get("verified", False)
    ctx.log(f"K8s check complete: verified={verified} ({result.get('retry_count', 0)} retries)")

    return {
        "status": "ok" if verified else "failed",
        "issues_found": len(result.get("cluster_issues", [])),
        "diagnosis": result.get("diagnosis", ""),
        "fix_applied": result.get("proposed_fix", ""),
        "fix_result": result.get("fix_result", ""),
        "verified": verified,
        "retries": result.get("retry_count", 0),
    }

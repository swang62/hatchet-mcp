"""Hatchet workflow: Kubernetes DevOps agent.

Triggered by the kb:k8s:monitor event. Runs the LangGraph K8s agent
which checks cluster health, diagnoses issues, and attempts fixes
(retries up to max_retries before giving up).
"""

from hatchet_sdk import Context

from src.langgraph.agents.k8s_devops import graph as k8s_graph


def run_k8s_check(input: dict, ctx: Context) -> dict:
    state = {
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
    ctx.log(
        f"K8s check complete: verified={verified} "
        f"({len(result.get('cluster_issues', []))} issues, "
        f"{result.get('retry_count', 0)} retries)"
    )

    return {
        "status": "ok" if verified else "failed",
        "issues_found": len(result.get("cluster_issues", [])),
        "diagnosis": result.get("diagnosis", ""),
        "fix_applied": result.get("proposed_fix", ""),
        "fix_result": result.get("fix_result", ""),
        "verified": verified,
        "retries": result.get("retry_count", 0),
    }

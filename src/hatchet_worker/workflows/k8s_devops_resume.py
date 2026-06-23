"""Hatchet workflow: resume a paused K8s DevOps agent.

Loads the LangGraph checkpoint by thread_id and sends the human's
approval/rejection decision via Command(resume=...).

If the graph hits another interrupt (retry), it returns needs_approval again.
If max_retries are exhausted, it returns manual_intervention_needed.
"""

from hatchet_sdk import Context
from langgraph.types import Command

from src.hatchet_worker.models import K8sDevOpsResumeInput
from src.langgraph.agents.k8s_devops import compile_graph
from src.shared.checkpointer import get_checkpointer
from src.shared.constants import DEVOPS_MAX_RETRIES, GRAPH_RECURSION_LIMIT


def run_k8s_resume(input: K8sDevOpsResumeInput, ctx: Context) -> dict:
    config = {
        "configurable": {"thread_id": input.thread_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }
    with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)

    resume_value: dict[str, object] = {"approved": input.approved}
    if input.command_override:
        resume_value["command_override"] = input.command_override

    ctx.log(f"Resuming K8s agent (thread={input.thread_id}, approved={input.approved})")

    result = graph.invoke(Command(resume=resume_value), config)  # type: ignore[arg-type]
    snapshot = graph.get_state(config)  # type: ignore[arg-type]

    if snapshot.next:
        ctx.log(f"Graph interrupted again at {snapshot.next} — next fix needs approval")
        return {
            "status": "needs_approval",
            "diagnosis": result.get("diagnosis", ""),
            "cluster_issues": result.get("cluster_issues", []),
            "proposed_fix": result.get("proposed_fix", ""),
            "thread_id": input.thread_id,
        }

    decision = result.get("decision", "")
    verified = result.get("verified", False)
    retry_count = result.get("retry_count", 0)
    max_retries = result.get("max_retries", DEVOPS_MAX_RETRIES)

    if decision == "rejected":
        ctx.log(f"Fix rejected by human (thread={input.thread_id})")
        return {
            "status": "rejected",
            "diagnosis": result.get("diagnosis", ""),
            "issues_found": len(result.get("cluster_issues", [])),
            "fix_result": "Fix rejected by human operator",
            "verified": False,
        }

    if not verified and retry_count >= max_retries:
        ctx.log(f"Max retries ({max_retries}) exhausted (thread={input.thread_id})")
        return {
            "status": "manual_intervention_needed",
            "diagnosis": result.get("diagnosis", ""),
            "issues_found": len(result.get("cluster_issues", [])),
            "last_fix_command": result.get("proposed_fix", ""),
            "last_fix_result": result.get("fix_result", ""),
            "retries_attempted": retry_count,
            "verified": False,
        }

    ctx.log(f"K8s check complete: verified={verified} ({retry_count} retries)")
    return {
        "status": "ok" if verified else "failed",
        "issues_found": len(result.get("cluster_issues", [])),
        "diagnosis": result.get("diagnosis", ""),
        "fix_applied": result.get("proposed_fix", ""),
        "fix_result": result.get("fix_result", ""),
        "verified": verified,
        "retries": retry_count,
    }

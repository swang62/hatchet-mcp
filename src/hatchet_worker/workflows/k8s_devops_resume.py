"""Hatchet workflow: resume a paused K8s DevOps agent.

Loads the LangGraph checkpoint by thread_id and sends the human's
approval/rejection decision via Command(resume=...).

If the graph hits another interrupt (retry), it returns needs_approval again.
If max_retries are exhausted, it returns manual_intervention_needed.
"""

from hatchet_sdk import Context
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from src.hatchet_worker.models import K8sDevOpsResumeInput
from src.langgraph.agents.k8s_devops import compile_graph
from src.shared.checkpointer import get_checkpointer
from src.shared.constants import DEVOPS_MAX_RETRIES, GRAPH_RECURSION_LIMIT, LOG_OUTPUT_MAX


def _trunc(text: str, maxlen: int = LOG_OUTPUT_MAX) -> str:
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "..."


def run_k8s_resume(input: K8sDevOpsResumeInput, ctx: Context) -> dict:
    config: RunnableConfig = {
        "configurable": {"thread_id": input.thread_id, "__ctx__": ctx},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }
    with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)

        resume_value: dict[str, object] = {"approved": input.approved}
        if input.command_override:
            resume_value["command_override"] = input.command_override

        ctx.log(f"Resuming agent: thread={input.thread_id} approved={input.approved}")

        result = graph.invoke(Command(resume=resume_value), config)
        snapshot = graph.get_state(config)

    if snapshot.next:
        diag = result.get("diagnosis", "")
        fix = result.get("proposed_fix", "")
        ctx.log(f"Graph interrupted again at {snapshot.next} — next fix: {fix}")
        return {
            "status": "needs_approval",
            "diagnosis": diag,
            "cluster_issues": result.get("cluster_issues", []),
            "proposed_fix": fix,
            "thread_id": input.thread_id,
        }

    decision = result.get("decision", "")
    verified = result.get("verified", False)
    retry_count = result.get("retry_count", 0)
    max_retries = result.get("max_retries", DEVOPS_MAX_RETRIES)
    fix_applied = result.get("proposed_fix", "")
    fix_result = result.get("fix_result", "")
    issues = result.get("cluster_issues", [])

    if decision == "rejected":
        ctx.log(f"Fix rejected by human (thread={input.thread_id})")
        return {
            "status": "rejected",
            "diagnosis": result.get("diagnosis", ""),
            "issues_found": len(issues),
            "fix_result": "Fix rejected by human operator",
            "verified": False,
        }

    if not verified and retry_count >= max_retries:
        ctx.log(f"Max retries exhausted ({retry_count}) (thread={input.thread_id})")
        return {
            "status": "manual_intervention_needed",
            "diagnosis": result.get("diagnosis", ""),
            "issues_found": len(issues),
            "last_fix_command": fix_applied,
            "last_fix_result": fix_result,
            "retries_attempted": retry_count,
            "verified": False,
        }

    ctx.log(f"Agent resumed: ok={verified} retries={retry_count} issues={len(issues)}")
    if fix_applied:
        ctx.log(f"Fix applied: {fix_applied}")
    if fix_result:
        ctx.log(f"Fix result: {_trunc(fix_result)}")

    return {
        "status": "ok" if verified else "failed",
        "issues_found": len(issues),
        "diagnosis": result.get("diagnosis", ""),
        "fix_applied": fix_applied,
        "fix_result": fix_result,
        "verified": verified,
        "retries": retry_count,
    }

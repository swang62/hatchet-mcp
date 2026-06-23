"""Hatchet workflow: K8s DevOps agent (HITL-enabled).

Triggered by hatchet.runs.create("k8s_devops", ...) from the MCP server.
Runs the LangGraph graph with a Postgres checkpointer.
If the LLM proposes a fix, execution pauses at attempt_fix (interrupt)
and returns the diagnosis + proposed_fix for human approval.
"""

import uuid

from hatchet_sdk import Context

from src.hatchet_worker.models import K8sDevOpsInput
from src.langgraph.agents.k8s_devops import _initial_state, compile_graph
from src.shared.checkpointer import get_checkpointer
from src.shared.constants import GRAPH_RECURSION_LIMIT


def run_k8s_check(input: K8sDevOpsInput, ctx: Context) -> dict:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": GRAPH_RECURSION_LIMIT}
    with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)
        state = _initial_state(input.task)
        result = graph.invoke(state, config)  # type: ignore[arg-type]
        snapshot = graph.get_state(config)  # type: ignore[arg-type]

    if snapshot.next:
        ctx.log(
            f"Graph interrupted at {snapshot.next} — awaiting human approval (thread={thread_id})"
        )
        return {
            "status": "needs_approval",
            "diagnosis": result.get("diagnosis", ""),
            "cluster_issues": result.get("cluster_issues", []),
            "proposed_fix": result.get("proposed_fix", ""),
            "thread_id": thread_id,
        }

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

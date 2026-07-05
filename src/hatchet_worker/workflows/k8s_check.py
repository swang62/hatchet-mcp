"""Hatchet workflow: run the K8s DevOps LangGraph agent."""

from hatchet_sdk import Context
from langchain_core.runnables.config import RunnableConfig

from src.hatchet_worker.models import K8sDevOpsInput
from src.langgraph.agents.k8s_devops import compile_graph, initial_state
from src.shared.checkpointer import get_checkpointer
from src.shared.constants import GRAPH_RECURSION_LIMIT
from src.shared.enums import WorkflowStatus
from src.shared.scheduling import send_approval_notification
from src.shared.utils import trunc


def k8s_check(input: K8sDevOpsInput, ctx: Context) -> dict:
    thread_id = ctx.workflow_run_id
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "__ctx__": ctx},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }
    ctx.log(f"Agent starting: task={input.task!r} thread={thread_id}")

    with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)
        existing = checkpointer.get_tuple(config)

        if existing is None:
            state = initial_state(input.task)
            ctx.log("No existing checkpoint -- starting fresh graph")
            result = graph.invoke(state, config)
        else:
            ctx.log(f"Found existing checkpoint -- resuming (thread={thread_id})")
            result = graph.invoke(None, config)

        snapshot = graph.get_state(config)

    if snapshot.next:
        ctx.log(f"Graph paused at {snapshot.next} -- awaiting approval (thread={thread_id})")
        diag = result.get("diagnosis", "")
        fix = result.get("proposed_fix", "")
        ctx.log(f"Diagnosis: {diag}")
        ctx.log(f"Proposed fix: {fix}")
        if input.source == "cron":
            send_approval_notification(result, thread_id)
        return {
            "status": WorkflowStatus.NEEDS_APPROVAL,
            "diagnosis": diag,
            "cluster_issues": result.get("cluster_issues", []),
            "proposed_fix": fix,
            "thread_id": thread_id,
        }

    issues = result.get("cluster_issues", [])
    verified = result.get("verified", False)
    is_ok = verified or not issues
    fix_applied = result.get("proposed_fix", "")
    fix_result = result.get("fix_result", "")
    retry_count = result.get("retry_count", 0)

    ctx.log(
        f"Agent complete: ok={is_ok} verified={verified} issues={len(issues)} retries={retry_count}"
    )
    if fix_applied:
        ctx.log(f"Fix applied: {fix_applied}")
    if fix_result:
        ctx.log(f"Fix result: {trunc(fix_result)}")

    return {
        "status": WorkflowStatus.OK if is_ok else WorkflowStatus.FAILED,
        "issues_found": len(issues),
        "diagnosis": result.get("diagnosis", ""),
        "fix_applied": fix_applied,
        "fix_result": fix_result,
        "verified": verified,
        "retries": retry_count,
    }

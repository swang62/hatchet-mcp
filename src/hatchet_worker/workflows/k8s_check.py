"""Hatchet workflow: run the K8s DevOps LangGraph agent."""

from hatchet_sdk import Context
from langchain_core.runnables.config import RunnableConfig

from src.hatchet_worker.models import K8sDevOpsInput
from src.langgraph.agents.k8s_devops import compile_graph, initial_state
from src.shared.checkpointer import get_checkpointer
from src.shared.enums import WorkflowStatus
from src.shared.responses import K8sAgentResult
from src.shared.scheduling import send_approval_notification
from src.shared.utils import trunc


def k8s_check(input: K8sDevOpsInput, ctx: Context) -> dict:
    thread_id = ctx.workflow_run_id
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "__ctx__": ctx},
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
        diag = result.get("diagnosis", "")
        fix = result.get("proposed_fix", "")
        if input.source == "cron":
            send_approval_notification(result, thread_id)
        return K8sAgentResult(
            status=WorkflowStatus.NEEDS_APPROVAL,
            diagnosis=diag,
            cluster_issues=result.get("cluster_issues", []),
            proposed_fix=fix,
            thread_id=thread_id,
        ).model_dump()

    issues = result.get("cluster_issues", [])
    is_ok = not issues
    fix_applied = result.get("proposed_fix", "")
    fix_result = result.get("fix_result", "")
    failed_retries = result.get("failed_retries", 0)

    ctx.log(f"Agent complete: ok={is_ok} issues={len(issues)} retries={failed_retries}")
    if fix_applied:
        ctx.log(f"Fix applied: {fix_applied}")
    if fix_result:
        ctx.log(f"Fix result: {trunc(fix_result)}")

    return K8sAgentResult(
        status=WorkflowStatus.OK if is_ok else WorkflowStatus.FAILED,
        diagnosis=result.get("diagnosis", ""),
        issues_found=len(issues),
        failed_retries=failed_retries,
        fix_applied=fix_applied,
        fix_result=fix_result,
    ).model_dump()

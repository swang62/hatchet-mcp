"""Hatchet workflow: manage K8s DevOps agent approval lifecycle."""

from hatchet_sdk import Context
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from src.hatchet_worker.models import K8sResumeInput
from src.langgraph.agents.k8s_devops import compile_graph
from src.shared.checkpointer import get_checkpointer, list_paused_threads
from src.shared.constants import K8S_MAX_RETRIES
from src.shared.enums import ResumeAction, WorkflowStatus
from src.shared.responses import K8sAgentResult
from src.shared.utils import trunc


def _run_resume_approval(input: K8sResumeInput, ctx: Context) -> dict:
    approved = input.action == ResumeAction.APPROVE
    config: RunnableConfig = {
        "configurable": {"thread_id": input.thread_id, "__ctx__": ctx},
    }
    with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)
        resume_value: dict[str, object] = {"approved": approved}
        if input.command_override:
            resume_value["command_override"] = input.command_override
        ctx.log(f"Resuming agent: thread={input.thread_id} approved={approved}")
        result = graph.invoke(Command(resume=resume_value), config)
        snapshot = graph.get_state(config)

    if snapshot.next:
        diag = result.get("diagnosis", "")
        fix = result.get("proposed_fix", "")
        ctx.log(f"Graph interrupted again at {snapshot.next} -- next fix: {fix}")
        return K8sAgentResult(
            status=WorkflowStatus.NEEDS_APPROVAL,
            diagnosis=diag,
            cluster_issues=result.get("cluster_issues", []),
            proposed_fix=fix,
            thread_id=input.thread_id,
        ).model_dump()

    rejected = result.get("rejected", False)
    failed_retries = result.get("failed_retries", 0)
    fix_applied = result.get("proposed_fix", "")
    fix_result = result.get("fix_result", "")
    issues = result.get("cluster_issues", [])

    if rejected:
        ctx.log(f"Fix rejected by human (thread={input.thread_id})")
        return K8sAgentResult(
            status=WorkflowStatus.REJECTED,
            diagnosis=result.get("diagnosis", ""),
            issues_found=len(issues),
            failed_retries=failed_retries,
            fix_result="Fix rejected by human operator",
        ).model_dump()

    is_ok = not issues
    if not is_ok and failed_retries >= K8S_MAX_RETRIES:
        ctx.log(f"Max retries exhausted ({failed_retries}) (thread={input.thread_id})")
        return K8sAgentResult(
            status=WorkflowStatus.MANUAL_INTERVENTION,
            diagnosis=result.get("diagnosis", ""),
            issues_found=len(issues),
            failed_retries=failed_retries,
            fix_applied=fix_applied,
            fix_result=fix_result,
        ).model_dump()

    ctx.log(f"Agent resumed: ok={is_ok} retries={failed_retries} issues={len(issues)}")
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


def _handle_list(ctx: Context) -> dict:
    result = list_paused_threads()
    ctx.log(f"list: {len(result)} paused threads")
    return {"result": result}


def _handle_status(thread_id: str, ctx: Context) -> dict:
    try:
        with get_checkpointer() as cp:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            existing = cp.get_tuple(config)
            if existing is None:
                ctx.log(f"status: thread {thread_id} not found")
                return {"status": WorkflowStatus.NOT_FOUND, "thread_id": thread_id}

            g = compile_graph(cp)
            snapshot = g.get_state(config)
            if snapshot.next:
                interrupts = []
                for t in snapshot.tasks or []:
                    for i in t.interrupts or []:
                        interrupts.append(i.value)
                ctx.log(f"status: thread {thread_id} pending_approval")
                return {
                    "status": WorkflowStatus.PENDING_APPROVAL,
                    "thread_id": thread_id,
                    "pending_tasks": [t.name for t in (snapshot.tasks or [])],
                    "interrupt_values": interrupts,
                }
            ctx.log(f"status: thread {thread_id} completed")
            return {"status": WorkflowStatus.COMPLETED, "thread_id": thread_id}
    except ValueError as e:
        ctx.log(f"status: thread {thread_id} error: {e}")
        return {"error": str(e), "thread_id": thread_id}


def _handle_cleanup(thread_id: str, ctx: Context) -> dict:
    try:
        with get_checkpointer() as cp:
            cp.delete_thread(thread_id)
        ctx.log(f"cleanup: deleted thread {thread_id}")
        return {"status": WorkflowStatus.DELETED, "thread_id": thread_id}
    except ValueError as e:
        ctx.log(f"cleanup: thread {thread_id} error: {e}")
        return {"error": str(e), "thread_id": thread_id}


def k8s_resume(input: K8sResumeInput, ctx: Context) -> dict:
    ctx.log(f"Resume action: {input.action} thread={input.thread_id}")
    if input.action == "list":
        return _handle_list(ctx)
    if input.action == "status":
        return _handle_status(input.thread_id, ctx)
    if input.action == "cleanup":
        return _handle_cleanup(input.thread_id, ctx)
    return _run_resume_approval(input, ctx)

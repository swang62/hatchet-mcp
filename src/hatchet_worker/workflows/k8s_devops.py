"""Hatchet workflow: K8s DevOps agent (HITL-enabled).

Triggered by hatchet.runs.create("k8s_devops", ...) from the MCP server.
Runs the LangGraph graph with a Postgres checkpointer.
If the LLM proposes a fix, execution pauses at attempt_fix (interrupt)
and returns the diagnosis + proposed_fix for human approval.
"""

import os

import httpx
from hatchet_sdk import Context
from langchain_core.runnables.config import RunnableConfig

from src.hatchet_worker.models import K8sDevOpsInput
from src.langgraph.agents.k8s_devops import _initial_state, compile_graph
from src.shared.checkpointer import get_checkpointer
from src.shared.constants import GRAPH_RECURSION_LIMIT, LOG_OUTPUT_MAX


def _trunc(text: str, maxlen: int = LOG_OUTPUT_MAX) -> str:
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "..."


def _send_notification(result: dict, thread_id: str) -> None:
    url = os.getenv("NOTIFICATION_URL", "")
    if not url:
        return
    diagnosis = result.get("diagnosis", "")
    issues = result.get("cluster_issues", [])
    proposed_fix = result.get("proposed_fix", "")
    issue_lines = "\n".join(
        f"\u2022 {i.get('namespace', '?')}/{i.get('name', '?')}: {i.get('reason', '?')}"
        for i in issues[:10]
    )
    body = (
        f"Diagnosis: {diagnosis}\n\n"
        f"Issues ({len(issues)}):\n{issue_lines}\n\n"
        f"Proposed fix: {proposed_fix}\n\n"
        f"Thread: {thread_id}\n"
        f"Use resume_devops_agent to approve or reject."
    )
    try:
        httpx.post(
            url,
            json={
                "title": f"K8s DevOps: {len(issues)} issue(s) found \u2014 approval needed",
                "message": body,
                "tags": ["warning", "kubernetes"],
                "priority": 4,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"Failed to send notification: {e}")


def run_k8s_check(input: K8sDevOpsInput, ctx: Context) -> dict:
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
            state = _initial_state(input.task)
            ctx.log("No existing checkpoint — starting fresh graph")
            result = graph.invoke(state, config)
        else:
            ctx.log(f"Found existing checkpoint — resuming (thread={thread_id})")
            result = graph.invoke(None, config)

        snapshot = graph.get_state(config)

    if snapshot.next:
        ctx.log(f"Graph paused at {snapshot.next} — awaiting approval (thread={thread_id})")
        diag = result.get("diagnosis", "")
        fix = result.get("proposed_fix", "")
        ctx.log(f"Diagnosis: {diag}")
        ctx.log(f"Proposed fix: {fix}")
        if input.source == "cron":
            _send_notification(result, thread_id)
        return {
            "status": "needs_approval",
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
        ctx.log(f"Fix result: {_trunc(fix_result)}")

    return {
        "status": "ok" if is_ok else "failed",
        "issues_found": len(issues),
        "diagnosis": result.get("diagnosis", ""),
        "fix_applied": fix_applied,
        "fix_result": fix_result,
        "verified": verified,
        "retries": retry_count,
    }

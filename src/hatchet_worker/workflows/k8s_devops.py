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
from src.shared.constants import GRAPH_RECURSION_LIMIT


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
        "configurable": {"thread_id": thread_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }
    with get_checkpointer() as checkpointer:
        graph = compile_graph(checkpointer)

        existing = checkpointer.get_tuple(config)
        if existing is None:
            state = _initial_state(input.task)
            result = graph.invoke(state, config)
        else:
            ctx.log(f"Resuming from checkpoint (thread={thread_id})")
            result = graph.invoke(None, config)

        snapshot = graph.get_state(config)

    if snapshot.next:
        ctx.log(
            f"Graph interrupted at {snapshot.next} \u2014 awaiting human approval (thread={thread_id})"
        )
        if input.source == "cron":
            _send_notification(result, thread_id)
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

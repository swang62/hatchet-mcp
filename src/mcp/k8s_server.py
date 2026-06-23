"""MCP server: Kubernetes debugging tools via Hatchet worker."""

from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.shared.checkpointer import get_checkpointer, list_paused_threads
from src.shared.constants import (
    K8S_DEFAULT_EVENT_LIMIT,
    K8S_DEFAULT_LOG_TAIL,
    K8S_DEVOPS_WORKFLOW,
    K8S_RESUME_WORKFLOW,
    K8S_TIMEOUT,
    K8S_TOOL_WORKFLOW,
    MCP_LOG_LEVEL,
)
from src.shared.hatchet import get_hatchet, run_sync_workflow

load_dotenv()

hatchet = get_hatchet()
server = FastMCP("k8s-devops", log_level=MCP_LOG_LEVEL)


@server.tool()
def check_pods(namespace: str = "", include_restarts: bool = True) -> dict[str, Any]:
    """List problem pods (CrashLoop, ImagePull, Error, high restarts)."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW,
        {
            "tool": "check_pods",
            "params": {"namespace": namespace, "include_restarts": include_restarts},
        },
    )


@server.tool()
def get_logs(
    pod: str, namespace: str, tail: int = K8S_DEFAULT_LOG_TAIL, container: str = ""
) -> str:
    """Get recent pod logs."""
    result = run_sync_workflow(
        K8S_TOOL_WORKFLOW,
        {
            "tool": "get_logs",
            "params": {"pod": pod, "namespace": namespace, "tail": tail, "container": container},
        },
    )
    return result.get("logs", "")


@server.tool()
def describe_pod(pod: str, namespace: str) -> dict:
    """Get full pod spec, status, container states, conditions."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "describe_pod", "params": {"pod": pod, "namespace": namespace}}
    )


@server.tool()
def get_events(namespace: str = "", limit: int = K8S_DEFAULT_EVENT_LIMIT) -> dict[str, Any]:
    """List Warning/Error events. Empty namespace = cluster-wide."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW,
        {"tool": "get_events", "params": {"namespace": namespace, "limit": limit}},
    )


@server.tool()
def debug_pod(pod: str, namespace: str, tail: int = K8S_DEFAULT_LOG_TAIL) -> dict:
    """One-shot: pod description + logs + events."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW,
        {"tool": "debug_pod", "params": {"pod": pod, "namespace": namespace, "tail": tail}},
    )


@server.tool()
def run_kubectl(kubectl_command: str) -> dict:
    """Run a kubectl command."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "run_kubectl", "params": {"command": kubectl_command}}
    )


@server.tool()
def get_deployments(namespace: str = "") -> dict[str, Any]:
    """List deployments with replica counts and conditions."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_deployments", "params": {"namespace": namespace}}
    )


@server.tool()
def get_statefulsets(namespace: str = "") -> dict[str, Any]:
    """List statefulsets with replica counts."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_statefulsets", "params": {"namespace": namespace}}
    )


@server.tool()
def get_daemonsets(namespace: str = "") -> dict[str, Any]:
    """List daemonsets with desired/current/ready counts."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_daemonsets", "params": {"namespace": namespace}}
    )


@server.tool()
def get_services(namespace: str = "") -> dict[str, Any]:
    """List services with type, cluster IP, and ports."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_services", "params": {"namespace": namespace}}
    )


@server.tool()
def get_ingresses(namespace: str = "") -> dict[str, Any]:
    """List ingress resources with host rules and TLS."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_ingresses", "params": {"namespace": namespace}}
    )


@server.tool()
def get_configmaps(namespace: str = "") -> dict[str, Any]:
    """List configmaps and their data keys."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_configmaps", "params": {"namespace": namespace}}
    )


@server.tool()
def get_secrets(namespace: str = "") -> dict[str, Any]:
    """List secrets (names, types, data keys only — never values)."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW, {"tool": "get_secrets", "params": {"namespace": namespace}}
    )


@server.tool()
def exec_in_pod(pod: str, namespace: str, command: str, timeout: int = K8S_TIMEOUT) -> dict:
    """Run a command inside a pod."""
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW,
        {
            "tool": "exec_in_pod",
            "params": {"pod": pod, "namespace": namespace, "command": command, "timeout": timeout},
        },
    )


@server.tool()
def run_devops_agent(task: str) -> dict:
    """Run the K8s devops agent: check, diagnose, propose fix, then pause for approval.

    Returns diagnosis and proposed_fix; the agent pauses before executing.
    Call resume_devops_agent(thread_id, approved=True) to proceed.
    """
    return run_sync_workflow(
        K8S_DEVOPS_WORKFLOW,
        {"task": task},
        task_name="agent",
        timeout=K8S_TIMEOUT,
    )


@server.tool()
def resume_devops_agent(thread_id: str, approved: bool, command_override: str = "") -> dict:
    """Resume a paused K8s devops agent.

    Args:
        thread_id: The thread_id from run_devops_agent's response.
        approved: True to execute the fix, False to reject it.
        command_override: Optional replacement for the proposed kubectl command.
    """
    return run_sync_workflow(
        K8S_RESUME_WORKFLOW,
        {
            "thread_id": thread_id,
            "approved": approved,
            "command_override": command_override,
        },
        task_name="resume",
        timeout=K8S_TIMEOUT,
    )


@server.tool()
def list_pending_approvals() -> list[dict]:
    """List all threads currently paused waiting for human approval."""
    return list_paused_threads()


@server.tool()
def get_approval_status(thread_id: str) -> dict:
    """Check the status of a specific approval thread.

    Returns the interrupt values (diagnosis, proposed_fix, cluster_issues) if
    pending, or indicates if the thread has completed or doesn't exist.
    """
    from src.langgraph.agents.k8s_devops import compile_graph

    try:
        with get_checkpointer() as cp:
            config = {"configurable": {"thread_id": thread_id}}
            existing = cp.get_tuple(config)  # type: ignore[arg-type]
            if existing is None:
                return {"status": "not_found", "thread_id": thread_id}

            g = compile_graph(cp)
            snapshot = g.get_state(config)  # type: ignore[arg-type]
            if snapshot.next:
                interrupts = []
                for t in snapshot.tasks or []:
                    for i in t.interrupts or []:
                        interrupts.append(i.value)
                return {
                    "status": "pending_approval",
                    "thread_id": thread_id,
                    "pending_tasks": [t.name for t in (snapshot.tasks or [])],
                    "interrupt_values": interrupts,
                }
            return {"status": "completed", "thread_id": thread_id}
    except ValueError as e:
        return {"error": str(e), "thread_id": thread_id}


@server.tool()
def cleanup_thread(thread_id: str) -> dict:
    """Delete a stale checkpoint thread (clean up abandoned paused agents)."""
    try:
        with get_checkpointer() as cp:
            cp.delete_thread(thread_id)
        return {"status": "deleted", "thread_id": thread_id}
    except ValueError as e:
        return {"error": str(e), "thread_id": thread_id}


if __name__ == "__main__":
    server.run(transport="stdio")

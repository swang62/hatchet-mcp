"""MCP server: Kubernetes debugging tools via Hatchet worker."""

from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.shared.hatchet import get_hatchet, run_sync_workflow

load_dotenv()

hatchet = get_hatchet()
server = FastMCP("k8s-devops", log_level="WARNING")
WORKFLOW_NAME = "k8s_tool"


@server.tool()
def check_pods(namespace: str = "", include_restarts: bool = True) -> dict[str, Any]:
    """List problem pods (CrashLoop, ImagePull, Error, high restarts)."""
    return run_sync_workflow(
        WORKFLOW_NAME,
        {
            "tool": "check_pods",
            "params": {"namespace": namespace, "include_restarts": include_restarts},
        },
    )


@server.tool()
def get_logs(pod: str, namespace: str, tail: int = 100, container: str = "") -> str:
    """Get recent pod logs."""
    result = run_sync_workflow(
        WORKFLOW_NAME,
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
        WORKFLOW_NAME, {"tool": "describe_pod", "params": {"pod": pod, "namespace": namespace}}
    )


@server.tool()
def get_events(namespace: str = "", limit: int = 50) -> dict[str, Any]:
    """List Warning/Error events. Empty namespace = cluster-wide."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_events", "params": {"namespace": namespace, "limit": limit}}
    )


@server.tool()
def debug_pod(pod: str, namespace: str, tail: int = 100) -> dict:
    """One-shot: pod description + logs + events."""
    return run_sync_workflow(
        WORKFLOW_NAME,
        {"tool": "debug_pod", "params": {"pod": pod, "namespace": namespace, "tail": tail}},
    )


@server.tool()
def run_kubectl(kubectl_command: str) -> dict:
    """Run a kubectl command."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "run_kubectl", "params": {"command": kubectl_command}}
    )


@server.tool()
def get_deployments(namespace: str = "") -> dict[str, Any]:
    """List deployments with replica counts and conditions."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_deployments", "params": {"namespace": namespace}}
    )


@server.tool()
def get_statefulsets(namespace: str = "") -> dict[str, Any]:
    """List statefulsets with replica counts."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_statefulsets", "params": {"namespace": namespace}}
    )


@server.tool()
def get_daemonsets(namespace: str = "") -> dict[str, Any]:
    """List daemonsets with desired/current/ready counts."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_daemonsets", "params": {"namespace": namespace}}
    )


@server.tool()
def get_services(namespace: str = "") -> dict[str, Any]:
    """List services with type, cluster IP, and ports."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_services", "params": {"namespace": namespace}}
    )


@server.tool()
def get_ingresses(namespace: str = "") -> dict[str, Any]:
    """List ingress resources with host rules and TLS."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_ingresses", "params": {"namespace": namespace}}
    )


@server.tool()
def get_configmaps(namespace: str = "") -> dict[str, Any]:
    """List configmaps and their data keys."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_configmaps", "params": {"namespace": namespace}}
    )


@server.tool()
def get_secrets(namespace: str = "") -> dict[str, Any]:
    """List secrets (names, types, data keys only — never values)."""
    return run_sync_workflow(
        WORKFLOW_NAME, {"tool": "get_secrets", "params": {"namespace": namespace}}
    )


@server.tool()
def exec_in_pod(pod: str, namespace: str, command: str, timeout: int = 30) -> dict:
    """Run a command inside a pod."""
    return run_sync_workflow(
        WORKFLOW_NAME,
        {
            "tool": "exec_in_pod",
            "params": {"pod": pod, "namespace": namespace, "command": command, "timeout": timeout},
        },
    )


@server.tool()
def run_devops_agent(task: str) -> dict:
    """Run the autonomous K8s devops agent: check, diagnose, fix, verify, retry."""
    hatchet.event.push("k8s:devops", {"task": task})
    return {
        "status": "accepted",
        "event": "k8s:devops",
        "message": f"Devops agent started for '{task}'. Check Hatchet dashboard for progress.",
    }


if __name__ == "__main__":
    server.run(transport="stdio")

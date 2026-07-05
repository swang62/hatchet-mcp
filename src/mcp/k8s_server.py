from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.shared.constants import (
    K8S_DEFAULT_EVENT_LIMIT,
    K8S_DEFAULT_LOG_TAIL,
    K8S_DEVOPS_WORKFLOW,
    K8S_RESUME_WORKFLOW,
    K8S_TIMEOUT,
    K8S_TOOL_WORKFLOW,
    MCP_LOG_LEVEL,
)
from src.shared.enums import InspectCommand, ResourceKind, ResumeAction
from src.shared.hatchet import get_hatchet, run_sync_workflow

load_dotenv()

hatchet = get_hatchet()
server = FastMCP("k8s-devops", log_level=MCP_LOG_LEVEL)


@server.tool()
def k8s_inspect(
    command: InspectCommand,
    resource: ResourceKind = ResourceKind.PODS,
    name: str = "",
    namespace: str = "",
    tail: int = K8S_DEFAULT_LOG_TAIL,
    container: str = "",
    limit: int = K8S_DEFAULT_EVENT_LIMIT,
    command_args: str = "",
    include_restarts: bool = True,
) -> dict[str, Any]:
    """Unified cluster inspection.

    Supports listing resources, describing pods, getting logs,
    fetching events, running exec commands, and listing problem pods.

    Args:
        command: What to do (list, describe, logs, events, exec, problem_pods).
        resource: Resource type for list/describe/logs/exec.
        name: Resource name (required for describe, logs, exec).
        namespace: Kubernetes namespace.
        tail: Number of log lines (logs only).
        container: Container name (logs/exec only).
        limit: Event limit (events only).
        command_args: Command to run inside pod (exec only).
        include_restarts: Include high-restart pods in results.
    """
    if command == InspectCommand.PROBLEM_PODS:
        return run_sync_workflow(
            K8S_TOOL_WORKFLOW,
            {
                "tool": "check_pods",
                "params": {"namespace": namespace, "include_restarts": include_restarts},
            },
        )

    if command == InspectCommand.LIST:
        if resource == ResourceKind.PODS:
            return run_sync_workflow(
                K8S_TOOL_WORKFLOW,
                {
                    "tool": "check_pods",
                    "params": {"namespace": namespace, "include_restarts": include_restarts},
                },
            )
        kind_map = {
            ResourceKind.DEPLOYMENTS: "get_deployments",
            ResourceKind.STATEFULSETS: "get_statefulsets",
            ResourceKind.DAEMONSETS: "get_daemonsets",
            ResourceKind.SERVICES: "get_services",
            ResourceKind.INGRESSES: "get_ingresses",
            ResourceKind.CONFIGMAPS: "get_configmaps",
            ResourceKind.SECRETS: "get_secrets",
        }
        tool = kind_map.get(resource)
        if not tool:
            return {"error": f"Unsupported resource for list: {resource}"}
        return run_sync_workflow(
            K8S_TOOL_WORKFLOW,
            {"tool": tool, "params": {"namespace": namespace}},
        )

    if command == InspectCommand.DESCRIBE:
        if resource != ResourceKind.PODS:
            return {"error": f"Unsupported resource for describe: {resource} (only pods supported)"}
        return run_sync_workflow(
            K8S_TOOL_WORKFLOW,
            {"tool": "describe_pod", "params": {"pod": name, "namespace": namespace}},
        )

    if command == InspectCommand.LOGS:
        return run_sync_workflow(
            K8S_TOOL_WORKFLOW,
            {
                "tool": "get_logs",
                "params": {
                    "pod": name,
                    "namespace": namespace,
                    "tail": tail,
                    "container": container,
                },
            },
        )

    if command == InspectCommand.EVENTS:
        return run_sync_workflow(
            K8S_TOOL_WORKFLOW,
            {"tool": "get_events", "params": {"namespace": namespace, "limit": limit}},
        )

    if command == InspectCommand.EXEC:
        return run_sync_workflow(
            K8S_TOOL_WORKFLOW,
            {
                "tool": "exec_in_pod",
                "params": {
                    "pod": name,
                    "namespace": namespace,
                    "command": command_args,
                    "timeout": K8S_TIMEOUT,
                },
            },
        )

    return {"error": f"Unknown command: {command}"}


@server.tool()
def k8s_run_agent(task: str) -> dict[str, Any]:
    """Run the K8s devops agent: check cluster, diagnose, propose fix, pause for approval.

    Read-only diagnostics run automatically. Mutating commands wait for
    human approval before execution.

    Args:
        task: Description of the cluster issue to diagnose and fix.
    """
    return run_sync_workflow(
        K8S_DEVOPS_WORKFLOW,
        {"task": task},
        task_name="agent",
        timeout=K8S_TIMEOUT,
    )


@server.tool()
def k8s_resume(
    action: ResumeAction,
    thread_id: str = "",
    command_override: str = "",
) -> dict[str, Any]:
    """Manage HITL approval threads.

    Actions:
        list: List all threads paused for approval.
        status: Check a specific thread's status.
        approve: Approve the proposed fix and execute it.
        reject: Reject the proposed fix.
        cleanup: Delete a stale thread.

    Args:
        action: What to do.
        thread_id: Required for status, approve, reject, cleanup.
        command_override: Replace the proposed kubectl command (approve only).
    """
    return run_sync_workflow(
        K8S_RESUME_WORKFLOW,
        {
            "action": action.value,
            "thread_id": thread_id,
            "command_override": command_override,
        },
        task_name="resume",
        timeout=K8S_TIMEOUT,
    )


@server.tool()
def k8s_exec_kubectl(kubectl_command: str) -> dict[str, Any]:
    """Run a raw kubectl command (escape hatch for anything not covered by k8s_inspect).

    Args:
        kubectl_command: The full kubectl command string, e.g. "kubectl get nodes".
    """
    return run_sync_workflow(
        K8S_TOOL_WORKFLOW,
        {"tool": "run_kubectl", "params": {"command": kubectl_command}},
    )


if __name__ == "__main__":
    server.run(transport="stdio")

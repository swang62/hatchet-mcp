"""MCP server for Kubernetes debugging and operations.

Two layers of tools:

1. **Simple data tools** — `check_pods`, `get_logs`, `describe_pod`,
   `get_events`, `debug_pod`, `apply_fix`. These are the building
   blocks. Use them when you want to inspect or operate on the
   cluster yourself.

2. **`run_devops_agent`** — fire-and-wait autonomous agent. It runs
   the langgraph graph end-to-end (check → diagnose → fix → verify →
   self-correct) in-process and returns when done. Use this when you
   want a complete answer with no back-and-forth.

Register in ~/.config/opencode/opencode.json:
    {
      "mcpServers": {
        "k8s-devops": {
          "command": "uv",
          "args": ["run", "python", "src/mcp/k8s_server.py"]
        }
      }
    }

Run directly: just k8s-mcp
"""

import subprocess

from mcp.server.fastmcp import FastMCP
from src.k8s import core_api, pod_logs, recent_events

server = FastMCP("k8s-devops", log_level="WARNING")


# ── helpers ──


def _list_problem_pods(namespace: str, include_restarts: bool) -> list[dict]:
    v1 = core_api()
    pods = v1.list_namespaced_pod(namespace) if namespace else v1.list_pod_for_all_namespaces()
    issues = []
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in (
                "CrashLoopBackOff",
                "Error",
                "ImagePullBackOff",
            ):
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,
                        "message": c.state.waiting.message or "",
                    }
                )
            if include_restarts and c.restart_count > 3:
                issues.append(
                    {
                        "kind": "pod_restart",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "restart_count": c.restart_count,
                    }
                )
    return issues


def _describe_pod(pod: str, namespace: str) -> dict:
    v1 = core_api()
    p = v1.read_namespaced_pod(name=pod, namespace=namespace)
    return {
        "name": p.metadata.name,
        "namespace": p.metadata.namespace,
        "node": p.spec.node_name,
        "phase": p.status.phase,
        "pod_ip": p.status.pod_ip,
        "containers": [
            {
                "name": c.name,
                "image": c.image,
                "ready": c.ready,
                "restart_count": c.restart_count,
                "state": c.state.to_dict() if c.state else None,
            }
            for c in (p.status.container_statuses or [])
        ],
        "conditions": [
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message,
            }
            for c in (p.status.conditions or [])
        ],
    }


def _run_kubectl(cmd: str) -> dict:
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


# ── simple MCP tools ──


@server.tool()
def check_pods(namespace: str = "", include_restarts: bool = True) -> list[dict]:
    """List pods with problems (CrashLoop, ImagePull, Error) or high restarts. Empty namespace = cluster-wide."""
    return _list_problem_pods(namespace, include_restarts)


@server.tool()
def get_logs(pod: str, namespace: str, tail: int = 100, container: str = "") -> str:
    """Get recent logs from a pod (last `tail` lines, optionally from a specific container)."""
    return pod_logs(pod, namespace, tail, container)


@server.tool()
def describe_pod(pod: str, namespace: str) -> dict:
    """Get full pod spec, status, container states, and conditions."""
    return _describe_pod(pod, namespace)


@server.tool()
def get_events(namespace: str = "", limit: int = 50) -> list[dict]:
    """List recent Warning/Error events. Empty namespace = cluster-wide."""
    return recent_events(namespace, limit)


@server.tool()
def debug_pod(pod: str, namespace: str, tail: int = 100) -> dict:
    """One-shot debug info: pod description + recent logs + recent events. Use this when you don't know what's wrong."""
    return {
        "describe": _describe_pod(pod, namespace),
        "logs": pod_logs(pod, namespace, tail, container=""),
        "events": recent_events(namespace=namespace, limit=20),
    }


@server.tool()
def apply_fix(kubectl_command: str) -> dict:
    """Run a kubectl command and return stdout/stderr/returncode. Example: 'kubectl rollout restart deployment/nginx -n default'."""
    return _run_kubectl(kubectl_command)


# ── autonomous agent (one-shot, in-process) ──


@server.tool()
def run_devops_agent(task: str) -> dict:
    """Run the autonomous K8s devops agent on a task. Checks the cluster, diagnoses issues with full context (logs + events + history), attempts fixes via kubectl, verifies, and self-corrects up to 3 times. Returns when done.

    Use this when you want a complete answer without manual tool chaining.

    Examples:
    - 'fix the broken pods in default namespace'
    - 'investigate why the api deployment is crash-looping'
    - 'heal the cluster'
    """
    from src.langgraph.agents.k8s_devops import graph

    state = {
        "task": task,
        "cluster_issues": [],
        "diagnosis": "",
        "proposed_fix": "",
        "fix_result": "",
        "verified": False,
        "retry_count": 0,
        "max_retries": 3,
        "decision": "",
    }
    result = graph.invoke(state)
    return {
        "task": task,
        "verified": result.get("verified", False),
        "diagnosis": result.get("diagnosis", ""),
        "proposed_fix": result.get("proposed_fix", ""),
        "fix_result": result.get("fix_result", ""),
        "retries": result.get("retry_count", 0),
        "issues_found": len(result.get("cluster_issues", [])),
        "decision": result.get("decision", ""),
    }


if __name__ == "__main__":
    server.run(transport="stdio")

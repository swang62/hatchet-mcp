"""Shared Kubernetes utilities.

Used by both LangGraph agents and MCP tools so kube-config loading
and client construction live in one place.
"""

from typing import Any

from kubernetes import client, config


def load_kube() -> None:
    """Load kubeconfig locally or in-cluster credentials."""
    try:
        config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()


def core_api() -> client.CoreV1Api:
    """Get a CoreV1Api client (loads config lazily)."""
    load_kube()
    return client.CoreV1Api()


def pod_logs(pod: str, namespace: str, tail: int = 100, container: str = "") -> str:
    """Fetch recent pod logs."""
    v1 = core_api()
    kwargs: dict[str, Any] = {"name": pod, "namespace": namespace, "tail_lines": tail}
    if container:
        kwargs["container"] = container
    return v1.read_namespaced_pod_log(**kwargs)


def recent_events(namespace: str = "", limit: int = 50) -> list[dict]:
    """List recent Warning/Error events. Empty namespace = cluster-wide."""
    v1 = core_api()
    events = (
        v1.list_namespaced_event(namespace, limit=limit)
        if namespace
        else v1.list_event_for_all_namespaces(limit=limit)
    )
    return [
        {
            "name": e.metadata.name,
            "namespace": e.metadata.namespace,
            "type": e.type,
            "reason": e.reason,
            "message": e.message,
            "count": e.count,
            "last_seen": e.last_timestamp.isoformat() if e.last_timestamp else None,
        }
        for e in events.items
        if e.type in ("Warning", "Error")
    ]

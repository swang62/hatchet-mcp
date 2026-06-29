"""Kubernetes client helpers."""

from typing import Any

from kubernetes import client, config

from src.shared.constants import (
    K8S_DEFAULT_EVENT_LIMIT,
    K8S_DEFAULT_LOG_TAIL,
    K8S_EVENT_FILTER_TYPES,
)


def load_kube() -> None:
    try:
        config.load_kube_config()
    except config.ConfigError:
        config.load_incluster_config()


def core_api() -> Any:
    load_kube()
    return client.CoreV1Api()


def pod_logs(
    pod: str, namespace: str, tail: int = K8S_DEFAULT_LOG_TAIL, container: str = ""
) -> str:
    v1 = core_api()
    kwargs: dict[str, Any] = {"name": pod, "namespace": namespace, "tail_lines": tail}
    if container:
        kwargs["container"] = container
    return v1.read_namespaced_pod_log(**kwargs)


def apps_api() -> Any:
    load_kube()
    return client.AppsV1Api()  # type: ignore[attr-defined]


def networking_api() -> Any:
    load_kube()
    return client.NetworkingV1Api()  # type: ignore[attr-defined]


def _active_pod_keys(v1: Any) -> set[str]:
    pods = v1.list_pod_for_all_namespaces(watch=False)
    return {f"{p.metadata.namespace}/{p.metadata.name}" for p in pods.items}


def recent_events(namespace: str = "", limit: int = K8S_DEFAULT_EVENT_LIMIT) -> list[dict]:
    v1 = core_api()
    events = (
        v1.list_namespaced_event(namespace, limit=limit)
        if namespace
        else v1.list_event_for_all_namespaces(limit=limit)
    )
    active_pods = _active_pod_keys(v1)

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
        if e.type in K8S_EVENT_FILTER_TYPES
        and (
            e.involved_object.kind != "Pod"
            or f"{e.involved_object.namespace}/{e.involved_object.name}" in active_pods
        )
    ]

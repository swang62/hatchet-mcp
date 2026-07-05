"""Kubernetes client helpers and resource listing functions."""

import subprocess
from typing import Any

from kubernetes import client, config

from src.shared.constants import (
    K8S_DEFAULT_EVENT_LIMIT,
    K8S_DEFAULT_LOG_TAIL,
    K8S_EVENT_FILTER_TYPES,
    K8S_FAILURE_REASONS,
    K8S_RESTART_THRESHOLD,
    K8S_TIMEOUT,
    KUBECTL_CMD,
)


def load_kube() -> None:
    try:
        config.load_kube_config()
    except config.ConfigError:
        config.load_incluster_config()


def core_api() -> Any:
    load_kube()
    return client.CoreV1Api()


def apps_api() -> Any:
    load_kube()
    return client.AppsV1Api()  # type: ignore[attr-defined]


def networking_api() -> Any:
    load_kube()
    return client.NetworkingV1Api()  # type: ignore[attr-defined]


# ── Pod operations ──


def pod_logs(
    pod: str, namespace: str, tail: int = K8S_DEFAULT_LOG_TAIL, container: str = ""
) -> str:
    v1 = core_api()
    kwargs: dict[str, Any] = {"name": pod, "namespace": namespace, "tail_lines": tail}
    if container:
        kwargs["container"] = container
    return v1.read_namespaced_pod_log(**kwargs)


def describe_pod(pod: str, namespace: str) -> dict:
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


def list_problem_pods(namespace: str = "", include_restarts: bool = True) -> list[dict]:
    """List pods with failing containers or excessive restarts."""
    v1 = core_api()
    pods = v1.list_namespaced_pod(namespace) if namespace else v1.list_pod_for_all_namespaces()
    issues: list[dict] = []
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            is_failing = c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS
            is_running = c.state.running is not None

            if is_failing:
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,
                        "message": c.state.waiting.message or "",
                    }
                )

            if include_restarts and c.restart_count > K8S_RESTART_THRESHOLD and not is_running:
                issues.append(
                    {
                        "kind": "pod_restart",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "restart_count": c.restart_count,
                    }
                )
    return issues


def exec_in_pod(pod: str, namespace: str, command: str, timeout: int = K8S_TIMEOUT) -> dict:
    """Run a command inside a pod via kubectl exec."""
    result = subprocess.run(
        [KUBECTL_CMD, "exec", pod, "-n", namespace, "--"] + command.split(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


# ── Events ──


def unhealthy_pod_keys(v1: Any) -> set[str]:
    pods = v1.list_pod_for_all_namespaces(watch=False)
    unhealthy: set[str] = set()
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS:
                unhealthy.add(f"{pod.metadata.namespace}/{pod.metadata.name}")
                break
    return unhealthy


def unhealthy_node_names(v1: Any) -> set[str]:
    nodes = v1.list_node(watch=False)
    unhealthy: set[str] = set()
    for n in nodes.items:
        ready = any(c.status == "True" for c in (n.status.conditions or []) if c.type == "Ready")
        if not ready:
            unhealthy.add(n.metadata.name)
    return unhealthy


def recent_events(namespace: str = "", limit: int = K8S_DEFAULT_EVENT_LIMIT) -> list[dict]:
    v1 = core_api()
    events = (
        v1.list_namespaced_event(namespace, limit=limit)
        if namespace
        else v1.list_event_for_all_namespaces(limit=limit)
    )
    unhealthy_pods = unhealthy_pod_keys(v1)
    unhealthy_nodes = unhealthy_node_names(v1)

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
            e.involved_object.kind == "Pod"
            and f"{e.involved_object.namespace}/{e.involved_object.name}" in unhealthy_pods
            or e.involved_object.kind == "Node"
            and e.involved_object.name in unhealthy_nodes
            or e.involved_object.kind not in ("Pod", "Node")
        )
    ]


# ── Workload listing ──


def list_deployments(namespace: str = "") -> list[dict]:
    apps = apps_api()
    deploys = (
        apps.list_deployment_for_all_namespaces()
        if not namespace
        else apps.list_namespaced_deployment(namespace)
    )
    result: list[dict] = []
    for d in deploys.items:
        conditions = {
            c.type: {"status": c.status, "reason": c.reason, "message": c.message}
            for c in (d.status.conditions or [])
        }
        result.append(
            {
                "name": d.metadata.name,
                "namespace": d.metadata.namespace,
                "replicas": d.spec.replicas,
                "ready": d.status.ready_replicas or 0,
                "available": d.status.available_replicas or 0,
                "up_to_date": d.status.updated_replicas or 0,
                "strategy": d.spec.strategy.type if d.spec.strategy else "RollingUpdate",
                "conditions": conditions,
                "age": d.metadata.creation_timestamp.isoformat()
                if d.metadata.creation_timestamp
                else "",
            }
        )
    return result


def list_statefulsets(namespace: str = "") -> list[dict]:
    apps = apps_api()
    sts_list = (
        apps.list_stateful_set_for_all_namespaces()
        if not namespace
        else apps.list_namespaced_stateful_set(namespace)
    )
    result: list[dict] = []
    for s in sts_list.items:
        result.append(
            {
                "name": s.metadata.name,
                "namespace": s.metadata.namespace,
                "replicas": s.spec.replicas,
                "ready": s.status.ready_replicas or 0,
                "current": s.status.current_replicas or 0,
                "updated": s.status.updated_replicas or 0,
                "service_name": s.spec.service_name,
                "age": s.metadata.creation_timestamp.isoformat()
                if s.metadata.creation_timestamp
                else "",
            }
        )
    return result


def list_daemonsets(namespace: str = "") -> list[dict]:
    apps = apps_api()
    ds_list = (
        apps.list_daemon_set_for_all_namespaces()
        if not namespace
        else apps.list_namespaced_daemon_set(namespace)
    )
    result: list[dict] = []
    for d in ds_list.items:
        result.append(
            {
                "name": d.metadata.name,
                "namespace": d.metadata.namespace,
                "desired": d.status.desired_number_scheduled or 0,
                "current": d.status.current_number_scheduled or 0,
                "ready": d.status.number_ready or 0,
                "available": d.status.number_available or 0,
                "age": d.metadata.creation_timestamp.isoformat()
                if d.metadata.creation_timestamp
                else "",
            }
        )
    return result


# ── Service / network listing ──


def list_services(namespace: str = "") -> list[dict]:
    v1 = core_api()
    svcs = (
        v1.list_service_for_all_namespaces()
        if not namespace
        else v1.list_namespaced_service(namespace)
    )
    result: list[dict] = []
    for s in svcs.items:
        ports = [
            {
                "name": p.name,
                "protocol": p.protocol,
                "port": p.port,
                "target_port": str(p.target_port) if p.target_port else "",
                "node_port": p.node_port,
            }
            for p in (s.spec.ports or [])
        ]
        result.append(
            {
                "name": s.metadata.name,
                "namespace": s.metadata.namespace,
                "type": s.spec.type,
                "cluster_ip": s.spec.cluster_ip,
                "cluster_ips": s.spec.cluster_ips or [],
                "ports": ports,
                "selector": s.spec.selector or {},
                "age": s.metadata.creation_timestamp.isoformat()
                if s.metadata.creation_timestamp
                else "",
            }
        )
    return result


def list_ingresses(namespace: str = "") -> list[dict]:
    net = networking_api()
    ingresses = (
        net.list_ingress_for_all_namespaces()
        if not namespace
        else net.list_namespaced_ingress(namespace)
    )
    result: list[dict] = []
    for ing in ingresses.items:
        rules = []
        for rule in ing.spec.rules or []:
            paths = [
                {
                    "path": p.path or "/",
                    "path_type": p.path_type or "ImplementationSpecific",
                    "service_name": p.backend.service.name if p.backend.service else "",
                    "service_port": p.backend.service.port.number
                    if p.backend.service and p.backend.service.port
                    else "",
                }
                for p in (rule.http.paths if rule.http else [])
            ]
            rules.append(
                {
                    "host": rule.host or "*",
                    "paths": paths,
                }
            )
        tls = [
            {
                "hosts": t.hosts or [],
                "secret_name": t.secret_name or "",
            }
            for t in (ing.spec.tls or [])
        ]
        result.append(
            {
                "name": ing.metadata.name,
                "namespace": ing.metadata.namespace,
                "rules": rules,
                "tls": tls,
                "age": ing.metadata.creation_timestamp.isoformat()
                if ing.metadata.creation_timestamp
                else "",
            }
        )
    return result


# ── Config / secrets listing ──


def list_configmaps(namespace: str = "") -> list[dict]:
    v1 = core_api()
    cms = (
        v1.list_config_map_for_all_namespaces()
        if not namespace
        else v1.list_namespaced_config_map(namespace)
    )
    return [
        {
            "name": cm.metadata.name,
            "namespace": cm.metadata.namespace,
            "keys": list(cm.data.keys()) if cm.data else [],
            "age": cm.metadata.creation_timestamp.isoformat()
            if cm.metadata.creation_timestamp
            else "",
        }
        for cm in cms.items
    ]


def list_secrets(namespace: str = "") -> list[dict]:
    v1 = core_api()
    secs = (
        v1.list_secret_for_all_namespaces()
        if not namespace
        else v1.list_namespaced_secret(namespace)
    )
    return [
        {
            "name": s.metadata.name,
            "namespace": s.metadata.namespace,
            "type": s.type or "Opaque",
            "keys": list(s.data.keys()) if s.data else [],
            "age": s.metadata.creation_timestamp.isoformat()
            if s.metadata.creation_timestamp
            else "",
        }
        for s in secs.items
    ]


# ── Raw kubectl ──


def run_kubectl(command: str, timeout: int = K8S_TIMEOUT) -> dict:
    """Run an arbitrary kubectl command and return the result."""
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }

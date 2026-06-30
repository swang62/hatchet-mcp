"""Hatchet workflow: K8s simple-tool operations.

Triggered via ``hatchet.admin.run_workflow("k8s_tool", …)`` from the MCP
server.  Dispatches to the appropriate tool function based on the ``tool``
parameter in the input payload.

This keeps all K8s tool execution inside the Hatchet worker so every
operation is visible in the dashboard.
"""

import subprocess

from hatchet_sdk import Context

from src.hatchet_worker.models import K8sToolInput
from src.shared.constants import K8S_FAILURE_REASONS, K8S_RESTART_THRESHOLD
from src.shared.k8s import apps_api, core_api, networking_api, pod_logs, recent_events

# ── helpers ──


def _list_problem_pods(namespace: str, include_restarts: bool) -> list[dict]:
    v1 = core_api()
    pods = v1.list_namespaced_pod(namespace) if namespace else v1.list_pod_for_all_namespaces()
    issues = []
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            is_failing = c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS  # type: ignore[union-attr]
            is_running = c.state.running is not None

            if is_failing:
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,  # type: ignore[union-attr]
                        "message": c.state.waiting.message or "",  # type: ignore[union-attr]
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


def _list_deployments(namespace: str) -> list[dict]:
    apps = apps_api()
    deploys = (
        apps.list_deployment_for_all_namespaces()
        if not namespace
        else apps.list_namespaced_deployment(namespace)
    )
    result = []
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


def _list_statefulsets(namespace: str) -> list[dict]:
    apps = apps_api()
    sts_list = (
        apps.list_stateful_set_for_all_namespaces()
        if not namespace
        else apps.list_namespaced_stateful_set(namespace)
    )
    result = []
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


def _list_daemonsets(namespace: str) -> list[dict]:
    apps = apps_api()
    ds_list = (
        apps.list_daemon_set_for_all_namespaces()
        if not namespace
        else apps.list_namespaced_daemon_set(namespace)
    )
    result = []
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


def _list_services(namespace: str) -> list[dict]:
    v1 = core_api()
    svcs = (
        v1.list_service_for_all_namespaces()
        if not namespace
        else v1.list_namespaced_service(namespace)
    )
    result = []
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


def _list_ingresses(namespace: str) -> list[dict]:
    net = networking_api()
    ingresses = (
        net.list_ingress_for_all_namespaces()
        if not namespace
        else net.list_namespaced_ingress(namespace)
    )
    result = []
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


def _list_configmaps(namespace: str) -> list[dict]:
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


def _list_secrets(namespace: str) -> list[dict]:
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


# ── dispatcher ──


def run_k8s_tool(input: K8sToolInput, ctx: Context) -> dict:
    params = input.params
    ctx.log(f"Running K8s tool: {input.tool}")

    if input.tool == "check_pods":
        return {
            "result": _list_problem_pods(
                params.get("namespace", ""),
                params.get("include_restarts", True),
            )
        }

    if input.tool == "get_logs":
        logs = pod_logs(
            params["pod"],
            params["namespace"],
            tail=params.get("tail", 100),
            container=params.get("container", ""),
        )
        return {"logs": logs}

    if input.tool == "describe_pod":
        return _describe_pod(params["pod"], params["namespace"])

    if input.tool == "get_events":
        return {"result": recent_events(params.get("namespace", ""), params.get("limit", 50))}

    if input.tool == "debug_pod":
        return {
            "describe": _describe_pod(params["pod"], params["namespace"]),
            "logs": pod_logs(
                params["pod"], params["namespace"], tail=params.get("tail", 100), container=""
            ),
            "events": recent_events(namespace=params.get("namespace", ""), limit=20),
        }

    if input.tool == "run_kubectl":
        result = subprocess.run(
            params["command"],
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

    # ── workload inspection tools ──

    if input.tool == "get_deployments":
        return {"result": _list_deployments(params.get("namespace", ""))}

    if input.tool == "get_statefulsets":
        return {"result": _list_statefulsets(params.get("namespace", ""))}

    if input.tool == "get_daemonsets":
        return {"result": _list_daemonsets(params.get("namespace", ""))}

    if input.tool == "get_services":
        return {"result": _list_services(params.get("namespace", ""))}

    if input.tool == "get_ingresses":
        return {"result": _list_ingresses(params.get("namespace", ""))}

    if input.tool == "get_configmaps":
        return {"result": _list_configmaps(params.get("namespace", ""))}

    if input.tool == "get_secrets":
        return {"result": _list_secrets(params.get("namespace", ""))}

    if input.tool == "exec_in_pod":
        result = subprocess.run(
            ["kubectl", "exec", params["pod"], "-n", params["namespace"], "--"]
            + params["command"].split(),
            capture_output=True,
            text=True,
            timeout=params.get("timeout", 30),
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    return {"error": f"Unknown tool: {input.tool}"}

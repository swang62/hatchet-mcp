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
from src.shared.constants import (
    K8S_CONTEXT_EVENT_LIMIT,
    K8S_DEFAULT_EVENT_LIMIT,
    K8S_DEFAULT_LOG_TAIL,
    K8S_FAILURE_REASONS,
    K8S_RESTART_THRESHOLD,
    K8S_TIMEOUT,
    KUBECTL_CMD,
    LOG_OUTPUT_MAX,
)
from src.shared.k8s import apps_api, core_api, networking_api, pod_logs, recent_events

# ── helpers ──


def _list_problem_pods(namespace: str, include_restarts: bool) -> list[dict]:
    v1 = core_api()
    pods = v1.list_namespaced_pod(namespace) if namespace else v1.list_pod_for_all_namespaces()
    issues = []
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS:  # type: ignore[union-attr]
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,  # type: ignore[union-attr]
                        "message": c.state.waiting.message or "",  # type: ignore[union-attr]
                    }
                )
            if include_restarts and c.restart_count > K8S_RESTART_THRESHOLD:
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


# ── helpers ──


def _trunc(text: str, maxlen: int = LOG_OUTPUT_MAX) -> str:
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "..."


# ── dispatcher ──


def run_k8s_tool(input: K8sToolInput, ctx: Context) -> dict:
    params = input.params
    ctx.log(f"Running K8s tool: {input.tool} params={params}")

    if input.tool == "check_pods":
        ns = params.get("namespace", "")
        issues = _list_problem_pods(ns, params.get("include_restarts", True))
        ctx.log(f"check_pods ns={ns!r}: {len(issues)} issues")
        return {"result": issues}

    if input.tool == "get_logs":
        pod = params["pod"]
        ns = params["namespace"]
        tail = params.get("tail", K8S_DEFAULT_LOG_TAIL)
        container = params.get("container", "")
        logs = pod_logs(pod, ns, tail=tail, container=container)
        ctx.log(f"get_logs {ns}/{pod} (tail={tail}): {len(logs)} chars")
        return {"logs": logs}

    if input.tool == "describe_pod":
        pod = params["pod"]
        ns = params["namespace"]
        desc = _describe_pod(pod, ns)
        ctx.log(f"describe_pod {ns}/{pod}: phase={desc.get('phase')}")
        return desc

    if input.tool == "get_events":
        ns = params.get("namespace", "")
        limit = params.get("limit", K8S_DEFAULT_EVENT_LIMIT)
        events = recent_events(ns, limit)
        ctx.log(f"get_events ns={ns!r}: {len(events)} events")
        return {"result": events}

    if input.tool == "debug_pod":
        pod = params["pod"]
        ns = params["namespace"]
        tail = params.get("tail", K8S_DEFAULT_LOG_TAIL)
        desc = _describe_pod(pod, ns)
        logs = pod_logs(pod, ns, tail=tail, container="")
        events = recent_events(ns, K8S_CONTEXT_EVENT_LIMIT)
        ctx.log(
            f"debug_pod {ns}/{pod}: phase={desc.get('phase')}, "
            f"logs={len(logs)} chars, events={len(events)}"
        )
        return {"describe": desc, "logs": logs, "events": events}

    if input.tool == "run_kubectl":
        cmd = params["command"]
        ctx.log(f"run_kubectl: {cmd}")
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=K8S_TIMEOUT,
        )
        ctx.log(
            f"run_kubectl exit={result.returncode} "
            f"stdout={_trunc(result.stdout)} "
            f"stderr={_trunc(result.stderr)}"
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    # ── workload inspection tools ──

    if input.tool == "get_deployments":
        ns = params.get("namespace", "")
        deploys = _list_deployments(ns)
        ctx.log(f"get_deployments ns={ns!r}: {len(deploys)} deployments")
        return {"result": deploys}

    if input.tool == "get_statefulsets":
        ns = params.get("namespace", "")
        sts = _list_statefulsets(ns)
        ctx.log(f"get_statefulsets ns={ns!r}: {len(sts)} statefulsets")
        return {"result": sts}

    if input.tool == "get_daemonsets":
        ns = params.get("namespace", "")
        ds = _list_daemonsets(ns)
        ctx.log(f"get_daemonsets ns={ns!r}: {len(ds)} daemonsets")
        return {"result": ds}

    if input.tool == "get_services":
        ns = params.get("namespace", "")
        svcs = _list_services(ns)
        ctx.log(f"get_services ns={ns!r}: {len(svcs)} services")
        return {"result": svcs}

    if input.tool == "get_ingresses":
        ns = params.get("namespace", "")
        ings = _list_ingresses(ns)
        ctx.log(f"get_ingresses ns={ns!r}: {len(ings)} ingresses")
        return {"result": ings}

    if input.tool == "get_configmaps":
        ns = params.get("namespace", "")
        cms = _list_configmaps(ns)
        ctx.log(f"get_configmaps ns={ns!r}: {len(cms)} configmaps")
        return {"result": cms}

    if input.tool == "get_secrets":
        ns = params.get("namespace", "")
        secs = _list_secrets(ns)
        ctx.log(f"get_secrets ns={ns!r}: {len(secs)} secrets")
        return {"result": secs}

    if input.tool == "exec_in_pod":
        pod = params["pod"]
        ns = params["namespace"]
        cmd = params["command"]
        ctx.log(f"exec_in_pod {ns}/{pod}: {cmd}")
        result = subprocess.run(
            [KUBECTL_CMD, "exec", pod, "-n", ns, "--"] + cmd.split(),
            capture_output=True,
            text=True,
            timeout=params.get("timeout", K8S_TIMEOUT),
        )
        ctx.log(
            f"exec_in_pod exit={result.returncode} "
            f"stdout={_trunc(result.stdout)} "
            f"stderr={_trunc(result.stderr)}"
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    if input.tool == "k8s_resume":
        action = params.get("action", "")
        thread_id = params.get("thread_id", "")
        ctx.log(f"k8s_resume: action={action} thread_id={thread_id}")

        if action == "list":
            from src.shared.checkpointer import list_paused_threads

            result = list_paused_threads()
            ctx.log(f"list: {len(result)} paused threads")
            return {"result": result}

        if action == "status":
            from langchain_core.runnables.config import RunnableConfig

            from src.langgraph.agents.k8s_devops import compile_graph
            from src.shared.checkpointer import get_checkpointer

            try:
                with get_checkpointer() as cp:
                    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
                    existing = cp.get_tuple(config)
                    if existing is None:
                        ctx.log(f"status: thread {thread_id} not found")
                        return {"status": "not_found", "thread_id": thread_id}

                    g = compile_graph(cp)
                    snapshot = g.get_state(config)
                    if snapshot.next:
                        interrupts = []
                        for t in snapshot.tasks or []:
                            for i in t.interrupts or []:
                                interrupts.append(i.value)
                        ctx.log(f"status: thread {thread_id} pending_approval")
                        return {
                            "status": "pending_approval",
                            "thread_id": thread_id,
                            "pending_tasks": [t.name for t in (snapshot.tasks or [])],
                            "interrupt_values": interrupts,
                        }
                    ctx.log(f"status: thread {thread_id} completed")
                    return {"status": "completed", "thread_id": thread_id}
            except ValueError as e:
                ctx.log(f"status: thread {thread_id} error: {e}")
                return {"error": str(e), "thread_id": thread_id}

        if action == "cleanup":
            from src.shared.checkpointer import get_checkpointer

            try:
                with get_checkpointer() as cp:
                    cp.delete_thread(thread_id)
                ctx.log(f"cleanup: deleted thread {thread_id}")
                return {"status": "deleted", "thread_id": thread_id}
            except ValueError as e:
                ctx.log(f"cleanup: thread {thread_id} error: {e}")
                return {"error": str(e), "thread_id": thread_id}

        ctx.log(f"k8s_resume: unknown action {action}")
        return {"error": f"Unknown resume action: {action}"}

    ctx.log(f"Unknown tool: {input.tool}")
    return {"error": f"Unknown tool: {input.tool}"}

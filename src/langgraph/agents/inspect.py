from datetime import datetime, timezone
from typing import Any

from src.shared.constants import (
    K8S_EVENT_LIMIT,
    K8S_FAILURE_REASONS,
    K8S_MAX_LOG_TAIL,
    K8S_MAX_PROBLEM_PODS,
    K8S_PENDING_THRESHOLD,
)
from src.shared.k8s import apps_api, describe_pod, pod_logs, recent_events


def check_pod_phase(v1: Any, issues: list[dict], pod: Any) -> None:
    if not pod.metadata.creation_timestamp:
        age = 0.0
    else:
        age = (datetime.now(timezone.utc) - pod.metadata.creation_timestamp).total_seconds()
    name = pod.metadata.name
    ns = pod.metadata.namespace

    if pod.status.phase == "Pending" and age > K8S_PENDING_THRESHOLD:
        reason = "Pending"
        message = ""
        for c in pod.status.container_statuses or []:
            if c.state.waiting:
                reason = c.state.waiting.reason
                message = c.state.waiting.message or ""
        issues.append(
            {
                "kind": "pending_pod",
                "name": name,
                "namespace": ns,
                "reason": reason,
                "message": message,
            }
        )
        return

    if pod.status.phase == "Running" and age > K8S_PENDING_THRESHOLD:
        all_ready = all(c.ready for c in (pod.status.container_statuses or []))
        if not all_ready:
            issues.append(
                {
                    "kind": "not_ready_pod",
                    "name": name,
                    "namespace": ns,
                    "reason": "Readiness probe failing",
                    "message": "",
                }
            )

    for c in pod.status.container_statuses or []:
        if c.state.terminated and c.state.terminated.exit_code != 0:
            issues.append(
                {
                    "kind": "terminated_container",
                    "name": name,
                    "namespace": ns,
                    "reason": c.state.terminated.reason + f" (exit {c.state.terminated.exit_code})",
                    "message": c.state.terminated.message or "",
                }
            )

    for c in pod.status.init_container_statuses or []:
        if c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS:
            issues.append(
                {
                    "kind": "init_container",
                    "name": name,
                    "namespace": ns,
                    "reason": c.state.waiting.reason,
                    "message": c.state.waiting.message or "",
                }
            )


def check_deployments(issues: list[dict]) -> None:
    apps = apps_api()
    deploys = apps.list_deployment_for_all_namespaces()
    for d in deploys.items:
        desired = d.spec.replicas or 1
        ready = d.status.ready_replicas or 0
        if ready < desired:
            issues.append(
                {
                    "kind": "deployment_mismatch",
                    "name": d.metadata.name,
                    "namespace": d.metadata.namespace,
                    "reason": f"{ready}/{desired} replicas ready",
                    "message": "",
                }
            )


def check_nodes(v1: Any, issues: list[dict]) -> None:
    for node in v1.list_node().items:
        for c in node.status.conditions or []:
            if c.status == "True" and c.type in ("MemoryPressure", "DiskPressure", "PIDPressure"):
                issues.append(
                    {
                        "kind": "node_pressure",
                        "name": node.metadata.name,
                        "namespace": "",
                        "reason": c.type,
                        "message": c.message or "",
                    }
                )


def check_pod_events(v1: Any, pod: Any, issues: list[dict]) -> None:
    """Check pod for Warning events indicating failures not in container status."""
    events = v1.list_namespaced_event(
        pod.metadata.namespace,
        field_selector=f"involvedObject.name={pod.metadata.name}",
    )
    for ev in events.items:
        if ev.type != "Warning":
            continue
        issues.append(
            {
                "kind": "pod_event",
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "reason": ev.reason,
                "message": ev.message or "",
            }
        )


def gather_context(issues: list[dict]) -> tuple[dict, list[dict], dict]:
    seen: set[tuple[str, str]] = set()
    for i in issues:
        namespace = i.get("namespace", "")
        name = i.get("name", "")
        if namespace and name:
            seen.add((namespace, name))
    problem_pods = list(seen)[:K8S_MAX_PROBLEM_PODS]

    logs: dict[str, str] = {}
    describes: dict[str, dict] = {}
    for namespace, name in problem_pods:
        key = f"{namespace}/{name}"

        # add logs
        try:
            logs[key] = pod_logs(name, namespace, tail=K8S_MAX_LOG_TAIL)
        except Exception as e:
            logs[key] = f"(failed to get logs: {e})"

        # add configurations
        try:
            describes[key] = describe_pod(name, namespace)
        except Exception as e:
            describes[key] = {"error": str(e)}

    return logs, recent_events(namespace="", limit=K8S_EVENT_LIMIT), describes

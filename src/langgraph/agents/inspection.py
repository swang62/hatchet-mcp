from datetime import datetime, timezone
from typing import Any

from src.shared.constants import (
    K8S_EVENT_LIMIT,
    K8S_FAILURE_REASONS,
    K8S_MAX_ISSUES,
    K8S_MAX_LOG_TAIL,
    K8S_MAX_PROBLEM_PODS,
    K8S_PENDING_THRESHOLD,
    K8S_RESTART_THRESHOLD,
)
from src.shared.k8s import apps_api, core_api, pod_logs, recent_events

from .schemas import K8sState


def _pod_age_seconds(pod: Any) -> float:
    if not pod.metadata.creation_timestamp:
        return 0
    return (datetime.now(timezone.utc) - pod.metadata.creation_timestamp).total_seconds()


def _check_pod_phase(v1: Any, issues: list[dict], pod: Any) -> None:
    age = _pod_age_seconds(pod)
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


def _check_deployments(issues: list[dict]) -> None:
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


def _check_nodes(v1: Any, issues: list[dict]) -> None:
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


def _check_pod_events(v1: Any, pod: Any, issues: list[dict]) -> None:
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


def check_cluster(state: K8sState) -> dict:
    v1 = core_api()
    issues: list[dict] = []
    pods = v1.list_pod_for_all_namespaces(watch=False)

    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS:
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,
                        "message": c.state.waiting.message or "",
                    }
                )
            if c.restart_count > K8S_RESTART_THRESHOLD:
                issues.append(
                    {
                        "kind": "pod_restart",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "restart_count": c.restart_count,
                    }
                )

        _check_pod_phase(v1, issues, pod)

        if not pod.status.container_statuses or any(
            c.state.waiting for c in (pod.status.container_statuses or [])
        ):
            _check_pod_events(v1, pod, issues)

    _check_deployments(issues)
    _check_nodes(v1, issues)

    for ev in recent_events(namespace="", limit=K8S_MAX_ISSUES):
        issues.append(
            {
                "kind": "event",
                "name": ev["name"],
                "namespace": ev["namespace"],
                "reason": ev["reason"],
                "message": ev["message"],
            }
        )
    return {"cluster_issues": issues[:K8S_MAX_ISSUES]}


def _gather_context(issues: list[dict]) -> tuple[dict, list[dict]]:
    problem_pods = [i for i in issues if i.get("kind") == "pod"][:K8S_MAX_PROBLEM_PODS]
    logs: dict[str, str] = {}
    for issue in problem_pods:
        key = f"{issue['namespace']}/{issue['name']}"
        try:
            logs[key] = pod_logs(issue["name"], issue["namespace"], tail=K8S_MAX_LOG_TAIL)
        except Exception as e:
            logs[key] = f"(failed to get logs: {e})"
    return logs, recent_events(namespace="", limit=K8S_EVENT_LIMIT)

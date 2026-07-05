"""Hatchet workflow: K8s tool operations.

Thin dispatcher that routes tool requests to the appropriate
function in ``src.shared.k8s``.  All K8s API logic lives in the
shared module so it can be reused by other workflows or agents.
"""

from hatchet_sdk import Context

from src.shared.constants import (
    K8S_EVENT_LIMIT,
    K8S_MAX_LOG_TAIL,
    K8S_TIMEOUT,
)
from src.shared.k8s import (
    describe_pod,
    exec_in_pod,
    list_configmaps,
    list_daemonsets,
    list_deployments,
    list_ingresses,
    list_problem_pods,
    list_secrets,
    list_services,
    list_statefulsets,
    pod_logs,
    recent_events,
    run_kubectl,
)
from src.shared.types import K8sToolInput
from src.shared.utils import trunc


def k8s_tools(input: K8sToolInput, ctx: Context) -> dict:
    params = input.params
    ctx.log(f"Running K8s tool: {input.tool} params={params}")

    if input.tool == "check_pods":
        ns = params.get("namespace", "")
        issues = list_problem_pods(ns, params.get("include_restarts", True))
        ctx.log(f"check_pods ns={ns!r}: {len(issues)} issues")
        return {"result": issues}

    if input.tool == "get_logs":
        pod = params["pod"]
        ns = params["namespace"]
        tail = params.get("tail", K8S_MAX_LOG_TAIL)
        container = params.get("container", "")
        logs = pod_logs(pod, ns, tail=tail, container=container)
        ctx.log(f"get_logs {ns}/{pod} (tail={tail}): {len(logs)} chars")
        return {"logs": logs}

    if input.tool == "describe_pod":
        pod = params["pod"]
        ns = params["namespace"]
        desc = describe_pod(pod, ns)
        ctx.log(f"describe_pod {ns}/{pod}: phase={desc.get('phase')}")
        return desc

    if input.tool == "get_events":
        ns = params.get("namespace", "")
        limit = params.get("limit", K8S_EVENT_LIMIT)
        events = recent_events(ns, limit)
        ctx.log(f"get_events ns={ns!r}: {len(events)} events")
        return {"result": events}

    if input.tool == "debug_pod":
        pod = params["pod"]
        ns = params["namespace"]
        tail = params.get("tail", K8S_MAX_LOG_TAIL)
        desc = describe_pod(pod, ns)
        logs = pod_logs(pod, ns, tail=tail, container="")
        events = recent_events(ns, K8S_EVENT_LIMIT)
        ctx.log(
            f"debug_pod {ns}/{pod}: phase={desc.get('phase')}, "
            f"logs={len(logs)} chars, events={len(events)}"
        )
        return {"describe": desc, "logs": logs, "events": events}

    if input.tool == "run_kubectl":
        cmd = params["command"]
        ctx.log(f"run_kubectl: {cmd}")
        result = run_kubectl(cmd, K8S_TIMEOUT)
        ctx.log(
            f"run_kubectl exit={result['returncode']} "
            f"stdout={trunc(result['stdout'])} "
            f"stderr={trunc(result['stderr'])}"
        )
        return result

    # ── workload listing ──

    if input.tool == "get_deployments":
        ns = params.get("namespace", "")
        deploys = list_deployments(ns)
        ctx.log(f"get_deployments ns={ns!r}: {len(deploys)} deployments")
        return {"result": deploys}

    if input.tool == "get_statefulsets":
        ns = params.get("namespace", "")
        sts = list_statefulsets(ns)
        ctx.log(f"get_statefulsets ns={ns!r}: {len(sts)} statefulsets")
        return {"result": sts}

    if input.tool == "get_daemonsets":
        ns = params.get("namespace", "")
        ds = list_daemonsets(ns)
        ctx.log(f"get_daemonsets ns={ns!r}: {len(ds)} daemonsets")
        return {"result": ds}

    if input.tool == "get_services":
        ns = params.get("namespace", "")
        svcs = list_services(ns)
        ctx.log(f"get_services ns={ns!r}: {len(svcs)} services")
        return {"result": svcs}

    if input.tool == "get_ingresses":
        ns = params.get("namespace", "")
        ings = list_ingresses(ns)
        ctx.log(f"get_ingresses ns={ns!r}: {len(ings)} ingresses")
        return {"result": ings}

    if input.tool == "get_configmaps":
        ns = params.get("namespace", "")
        cms = list_configmaps(ns)
        ctx.log(f"get_configmaps ns={ns!r}: {len(cms)} configmaps")
        return {"result": cms}

    if input.tool == "get_secrets":
        ns = params.get("namespace", "")
        secs = list_secrets(ns)
        ctx.log(f"get_secrets ns={ns!r}: {len(secs)} secrets")
        return {"result": secs}

    if input.tool == "exec_in_pod":
        pod = params["pod"]
        ns = params["namespace"]
        cmd = params["command"]
        ctx.log(f"exec_in_pod {ns}/{pod}: {cmd}")
        result = exec_in_pod(pod, ns, cmd, params.get("timeout", K8S_TIMEOUT))
        ctx.log(
            f"exec_in_pod exit={result['returncode']} "
            f"stdout={trunc(result['stdout'])} "
            f"stderr={trunc(result['stderr'])}"
        )
        return result

    ctx.log(f"Unknown tool: {input.tool}")
    return {"error": f"Unknown tool: {input.tool}"}

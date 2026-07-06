import json
import re
import subprocess
import time

from langgraph.types import interrupt

from src.shared.constants import (
    K8S_EXEC_TIMEOUT,
    K8S_FAILURE_REASONS,
    K8S_MAX_ISSUES,
    K8S_RESTART_THRESHOLD,
    K8S_VERIFY_TIMEOUT,
    LLM_SYSTEM_PROMPT,
)
from src.shared.k8s import core_api, recent_events
from src.shared.types import K8sState
from src.shared.utils import call_llm, is_fix_command

from .inspect import (
    check_deployments,
    check_nodes,
    check_pod_events,
    check_pod_phase,
    gather_context,
)

# -------------- Core workflow nodes --------------


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

        check_pod_phase(v1, issues, pod)

        if not pod.status.container_statuses or any(
            c.state.waiting for c in (pod.status.container_statuses or [])
        ):
            check_pod_events(v1, pod, issues)

    check_deployments(issues)
    check_nodes(v1, issues)

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

    result: dict = {"cluster_issues": issues[:K8S_MAX_ISSUES]}
    if is_fix_command(state.get("proposed_fix", "")) and state.get("fix_result") and issues:
        result["failed_retries"] = state.get("failed_retries", 0) + 1
    return result


def diagnose(state: K8sState) -> dict:
    if not state["cluster_issues"]:
        return {"diagnosis": "No issues found"}

    logs, events, configs = gather_context(state["cluster_issues"])

    history = ""
    if state.get("proposed_fix") or state.get("fix_result"):
        history = (
            f"Previous command: {state.get('proposed_fix', '(none)')}\n"
            f"Previous command output: {state.get('fix_result', '(none)')}\n"
        )

    user = (
        f"Task: {state.get('task', 'diagnose and fix cluster issues')}\n\n"
        f"Current cluster issues:\n{json.dumps(state['cluster_issues'], indent=2)}\n\n"
        f"Recent cluster events:\n{json.dumps(events, indent=2)}\n\n"
        f"Relevant pod configs:\n{json.dumps(configs, indent=2)}\n\n"
        f"Problem pod tail logs:\n{json.dumps(logs, indent=2)}\n\n"
        f"{history}\n"
        "Output your new diagnosis and proposed fix as JSON."
    )

    rsp = call_llm([("system", LLM_SYSTEM_PROMPT), ("human", user)])
    content = rsp.content if isinstance(rsp.content, str) else str(rsp.content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = {"diagnosis": content, "proposed_fix": ""}
        else:
            data = {"diagnosis": content, "proposed_fix": ""}

    return {
        "diagnosis": data.get("diagnosis", content).strip(),
        "proposed_fix": data.get("proposed_fix", "").strip(),
    }


def approve_fix(state: K8sState) -> dict:
    proposed = state.get("proposed_fix", "").strip()
    if not proposed:
        return {"fix_failed": True}

    human_input = interrupt(
        {
            "diagnosis": state.get("diagnosis", ""),
            "summary": (
                f"Issues found: {len(state.get('cluster_issues', []))} "
                f"in the cluster.\nDiagnosis: {state.get('diagnosis', '')}"
            ),
            "proposed_fix": proposed,
        }
    )

    if not human_input.get("approved"):
        return {"rejected": True}

    override = human_input.get("command_override", "")
    if override and override != proposed:
        return {"proposed_fix": override}
    return {}


def execute_fix(state: K8sState) -> dict:
    command = state.get("proposed_fix", "").strip()
    if not command:
        return {"fix_result": ""}

    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=K8S_EXEC_TIMEOUT
        )
        fix_result = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        fix_result = f"Command timed out after {K8S_EXEC_TIMEOUT}s"

    return {"fix_result": fix_result}


def wait_for_recovery(state: K8sState) -> dict:
    deadline = time.monotonic() + K8S_VERIFY_TIMEOUT
    waited = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep_for = min(2, remaining)
        time.sleep(sleep_for)
        waited += sleep_for
    return {"waited_for": f"{waited:.1f}s"}

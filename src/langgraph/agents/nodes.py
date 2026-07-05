import json
import os
import re
import subprocess
import time

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from pydantic import SecretStr

from src.shared.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    K8S_EXEC_TIMEOUT,
    K8S_FAILURE_REASONS,
    K8S_MAX_ISSUES,
    K8S_RESTART_THRESHOLD,
    K8S_VERIFY_TIMEOUT,
    LLM_SYSTEM_PROMPT,
    LLM_TEMPERATURE,
)
from src.shared.k8s import core_api, recent_events
from src.shared.types import K8sState

from .inspect import (
    check_deployments,
    check_nodes,
    check_pod_events,
    check_pod_phase,
    gather_context,
)

MUTATING_VERBS = {
    "apply",
    "attach",
    "create",
    "delete",
    "drain",
    "edit",
    "exec",
    "expose",
    "patch",
    "port-forward",
    "replace",
    "rollout",
    "run",
    "scale",
    "set",
    "taint",
}


def _is_read_only_command(command: str) -> bool:
    for verb in MUTATING_VERBS:
        if verb in command:
            return False
    return True


def _call_llm(messages: list[tuple[str, str]]) -> BaseMessage:
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", DEFAULT_LLM_MODEL),
        api_key=SecretStr(os.environ["OPENAI_API_KEY"]) if "OPENAI_API_KEY" in os.environ else None,
        base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_LLM_BASE_URL),
        temperature=LLM_TEMPERATURE,
        timeout=5,
        max_retries=3,
    )
    return llm.invoke(messages)


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
    return {"cluster_issues": issues[:K8S_MAX_ISSUES]}


def diagnose(state: K8sState) -> dict:
    if not state["cluster_issues"]:
        return {"diagnosis": "No issues found"}

    logs, events = gather_context(state["cluster_issues"])

    history = ""
    if state.get("diagnosis") or state.get("fix_result"):
        history = (
            f"\nPrevious fix attempt: {state.get('proposed_fix', '(LLM produced no fix command)')}\n"
            f"Previous fix result: {state.get('fix_result', '(none)')}\n"
            f"Previous diagnosis: {state.get('diagnosis', '(none)')}\n"
            "If the previous fix did not work, propose a DIFFERENT approach.\n"
        )

    user = (
        f"Task: {state.get('task', 'diagnose and fix cluster issues')}\n\n"
        f"Current cluster issues:\n{json.dumps(state['cluster_issues'], indent=2)}\n\n"
        f"Problem pod logs:\n{json.dumps(logs, indent=2)}\n\n"
        f"Recent cluster events:\n{json.dumps(events, indent=2)}\n"
        f"{history}\n"
        "Output the diagnosis and proposed fix as JSON."
    )

    rsp = _call_llm([("system", LLM_SYSTEM_PROMPT), ("human", user)])
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

    was_mutating = not _is_read_only_command(command)

    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=K8S_EXEC_TIMEOUT
        )
        fix_result = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        fix_result = f"Command timed out after {K8S_EXEC_TIMEOUT}s"

    result: dict[str, str | int] = {"fix_result": fix_result}
    if was_mutating:
        result["failed_retries"] = state.get("failed_retries", 0) + 1
    return result


def wait_for_recovery(state: K8sState) -> dict:
    deadline = time.monotonic() + K8S_VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining < 2:
            break
        time.sleep(min(2, remaining))
    return {}

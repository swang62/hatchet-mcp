import json
import os
import re
import subprocess
import time
from typing import Literal

from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from pydantic import SecretStr

from src.shared.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEVOPS_MAX_RETRIES,
    K8S_TIMEOUT,
    K8S_VERIFY_POLL_INTERVAL,
    LLM_TEMPERATURE,
)

from .inspection import _gather_context, _has_failure_pods
from .schemas import K8sState

MUTATING_VERBS = {
    "delete",
    "apply",
    "create",
    "patch",
    "replace",
    "edit",
    "set",
    "label",
    "annotate",
    "taint",
    "cordon",
    "uncordon",
    "drain",
    "rollout",
    "scale",
    "exec",
    "port-forward",
    "cp",
    "attach",
    "run",
    "expose",
}


def _is_read_only_command(command: str) -> bool:
    for verb in MUTATING_VERBS:
        if verb in command:
            return False
    return True


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", DEFAULT_LLM_MODEL),
        api_key=SecretStr(os.environ["OPENAI_API_KEY"]) if "OPENAI_API_KEY" in os.environ else None,
        base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_LLM_BASE_URL),
        temperature=LLM_TEMPERATURE,
    )


def diagnose(state: K8sState) -> dict:
    if not state["cluster_issues"]:
        return {"diagnosis": "No issues found"}

    logs, events = _gather_context(state["cluster_issues"])

    system = (
        "You are an automated Kubernetes remediation system.\n\n"
        "You have the full picture of the cluster — current pod states, events, and logs. "
        "Do NOT ask for more information, suggest debugging steps, or propose investigation. "
        "Output the exact kubectl command(s) to resolve the issue.\n\n"
        "Reply with valid JSON only. Do NOT wrap in markdown or code fences.\n"
        'Example: {"diagnosis": "Pod nginx-xyz in default is CrashLoopBackOff due to OOM", '
        '"proposed_fix": "kubectl delete pod nginx-xyz -n default"}\n\n'
        "Rules:\n"
        '- "diagnosis": 1-2 sentences identifying the root cause\n'
        '- "proposed_fix": a single kubectl command, or multiple commands joined with &&\n'
        '  Must start with "kubectl".\n'
        "  Do NOT use placeholders — use exact pod/deployment names from the data below."
    )

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

    rsp = _llm().invoke([("system", system), ("human", user)])
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

    if _is_read_only_command(proposed):
        return {}

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
    if state.get("rejected"):
        return {"fix_result": "Fix rejected by human operator", "verified": False}

    if state.get("fix_failed"):
        return {"fix_result": "No fix proposed", "retry_count": state.get("retry_count", 0) + 1}

    command = state.get("proposed_fix", "").strip()
    if not command:
        return {"fix_result": ""}

    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=K8S_TIMEOUT
        )
        fix_result = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        fix_result = f"Command timed out after {K8S_TIMEOUT}s"

    return {"fix_result": fix_result, "retry_count": state.get("retry_count", 0) + 1}


def verify_fix(state: K8sState) -> dict:
    if state.get("rejected"):
        return {"verified": False}

    deadline = time.monotonic() + K8S_TIMEOUT
    while time.monotonic() < deadline:
        if not _has_failure_pods():
            return {"verified": True}
        remaining = deadline - time.monotonic()
        if remaining < K8S_VERIFY_POLL_INTERVAL:
            break
        time.sleep(min(K8S_VERIFY_POLL_INTERVAL, remaining))

    return {"verified": False}


def decide(state: K8sState) -> Literal["done", "retry"]:
    if state.get("rejected"):
        return "done"
    if state["verified"]:
        return "done"
    if state.get("fix_failed"):
        return "retry"
    if state.get("retry_count", 0) < DEVOPS_MAX_RETRIES:
        return "retry"
    return "done"

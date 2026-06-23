"""K8s DevOps LangGraph: check, diagnose, fix, verify, retry up to N times.

Supports human-in-the-loop via interrupt() before every attempt_fix.
Use compile_graph(checkpointer) to enable HITL; compile_graph() for auto mode.
"""

import json
import os
import subprocess
import time
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import SecretStr

from src.shared.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEVOPS_MAX_RETRIES,
    K8S_CONTEXT_EVENT_LIMIT,
    K8S_DEFAULT_LOG_TAIL,
    K8S_FAILURE_REASONS,
    K8S_MAX_ISSUES,
    K8S_MAX_PROBLEM_PODS,
    K8S_RESTART_THRESHOLD,
    K8S_TIMEOUT,
    K8S_VERIFY_POLL_INTERVAL,
    LLM_TEMPERATURE,
)
from src.shared.k8s import core_api, pod_logs, recent_events


class K8sState(TypedDict):
    task: str
    cluster_issues: list[dict]
    diagnosis: str
    proposed_fix: str
    fix_result: str
    verified: bool
    retry_count: int
    max_retries: int
    decision: str


def _initial_state(task: str) -> K8sState:
    return {
        "task": task,
        "cluster_issues": [],
        "diagnosis": "",
        "proposed_fix": "",
        "fix_result": "",
        "verified": False,
        "retry_count": 0,
        "max_retries": DEVOPS_MAX_RETRIES,
        "decision": "",
    }


def check_cluster(state: K8sState) -> dict:
    v1 = core_api()
    issues = []
    pods = v1.list_pod_for_all_namespaces(watch=False)
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
            if c.restart_count > K8S_RESTART_THRESHOLD:
                issues.append(
                    {
                        "kind": "pod_restart",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "restart_count": c.restart_count,
                    }
                )
    for ev in v1.list_event_for_all_namespaces(watch=False).items:
        if ev.type in ("Warning", "Error"):
            issues.append(
                {
                    "kind": "event",
                    "name": ev.metadata.name,
                    "namespace": ev.metadata.namespace,
                    "reason": ev.reason,
                    "message": ev.message,
                }
            )
    return {"cluster_issues": issues[:K8S_MAX_ISSUES]}


def _gather_context(issues: list[dict]) -> tuple[dict, list[dict]]:
    problem_pods = [i for i in issues if i.get("kind") == "pod"][:K8S_MAX_PROBLEM_PODS]
    logs: dict[str, str] = {}
    for issue in problem_pods:
        key = f"{issue['namespace']}/{issue['name']}"
        try:
            logs[key] = pod_logs(issue["name"], issue["namespace"], tail=K8S_DEFAULT_LOG_TAIL)
        except Exception as e:  # noqa: BLE001
            logs[key] = f"(failed to get logs: {e})"
    return logs, recent_events(namespace="", limit=K8S_CONTEXT_EVENT_LIMIT)


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", DEFAULT_LLM_MODEL),
        api_key=SecretStr(os.environ["OPENAI_API_KEY"]) if "OPENAI_API_KEY" in os.environ else None,
        base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_LLM_BASE_URL),
        temperature=LLM_TEMPERATURE,
    )


def diagnose(state: K8sState) -> dict:
    if not state["cluster_issues"]:
        return {"diagnosis": "No issues found", "decision": "done"}

    logs, events = _gather_context(state["cluster_issues"])

    system = (
        "You are an automated Kubernetes remediation system. "
        "You NEVER give advice or explanations — you only output the exact command to run.\n\n"
        "Reply with valid JSON. Do NOT wrap it in markdown or code fences.\n"
        'Example: {"diagnosis": "Pod nginx-xyz in default is CrashLoopBackOff due to OOM", '
        '"proposed_fix": "kubectl delete pod nginx-xyz -n default"}\n\n'
        "Rules:\n"
        '- "diagnosis": 1-2 sentences identifying the problem\n'
        '- "proposed_fix": the EXACT kubectl command to execute. Must start with "kubectl".\n'
        "  If multiple steps are needed, join with &&."
    )

    history = ""
    if state.get("proposed_fix"):
        history = (
            f"\nPrevious fix attempt: {state['proposed_fix']}\n"
            f"Previous fix result: {state.get('fix_result', '(none)')}\n"
            f"Previous diagnosis: {state.get('diagnosis', '(none)')}\n"
            "If the previous fix did not work, propose a DIFFERENT approach.\n"
        )

    user = (
        f"User task: {state.get('task', 'diagnose and fix cluster issues')}\n\n"
        f"Cluster issues:\n{json.dumps(state['cluster_issues'], indent=2)}\n\n"
        f"Recent logs for problem pods:\n{json.dumps(logs, indent=2)}\n\n"
        f"Recent cluster events:\n{json.dumps(events, indent=2)}\n"
        f"{history}\n"
        "What is the diagnosis and proposed fix?"
    )

    rsp = _llm().invoke([("system", system), ("human", user)])
    content = rsp.content if isinstance(rsp.content, str) else str(rsp.content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Hunt for JSON inside markdown code fences or backticks
        import re

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
        "decision": "fix",
    }


def attempt_fix(state: K8sState) -> dict:
    proposed_fix = state.get("proposed_fix", "").strip()
    if not proposed_fix:
        return {
            "fix_result": "No fix proposed",
            "decision": "failed",
            "retry_count": state.get("retry_count", 0) + 1,
        }

    human_input = interrupt(
        {
            "diagnosis": state.get("diagnosis", ""),
            "summary": (
                f"Issues found: {len(state.get('cluster_issues', []))} "
                f"in the cluster.\nDiagnosis: {state.get('diagnosis', '')}"
            ),
            "proposed_fix": proposed_fix,
        }
    )

    if not human_input.get("approved"):
        return {
            "fix_result": "Fix rejected by human operator",
            "verified": False,
            "decision": "rejected",
        }

    command = human_input.get("command_override", proposed_fix)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=K8S_TIMEOUT
        )
        fix_result = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        fix_result = f"Command timed out after {K8S_TIMEOUT}s"

    return {"fix_result": fix_result, "retry_count": state.get("retry_count", 0) + 1}


def _has_failure_pods() -> bool:
    v1 = core_api()
    for pod in v1.list_pod_for_all_namespaces(watch=False).items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in K8S_FAILURE_REASONS:  # type: ignore[union-attr]
                return True
    return False


def verify_fix(state: K8sState) -> dict:
    if state.get("decision") == "rejected":
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
    if state.get("decision") in ("rejected", "failed"):
        return "done"
    if state["verified"]:
        return "done"
    if state.get("retry_count", 0) < state.get("max_retries", DEVOPS_MAX_RETRIES):
        return "retry"
    return "done"


def _build_graph() -> StateGraph:
    graph = (
        StateGraph(K8sState)  # type: ignore[invalid-argument-type]
        .add_node("check_cluster", check_cluster)
        .add_node("diagnose", diagnose)
        .add_node("attempt_fix", attempt_fix)
        .add_node("verify_fix", verify_fix)
        .add_conditional_edges(
            "check_cluster",
            lambda s: "diagnose" if s["cluster_issues"] else "done",
            {"diagnose": "diagnose", "done": END},
        )
        .add_edge("diagnose", "attempt_fix")
        .add_edge("attempt_fix", "verify_fix")
        .add_conditional_edges(
            "verify_fix",
            decide,
            {"done": END, "retry": "check_cluster"},
        )
        .add_edge(START, "check_cluster")
    )
    return graph


def compile_graph(checkpointer=None) -> CompiledStateGraph:
    return _build_graph().compile(checkpointer=checkpointer)

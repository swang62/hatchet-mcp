"""Kubernetes DevOps LangGraph graph.

Autonomous workflow: check cluster → diagnose (with logs + events +
previous-fix history) → attempt fix → verify → retry up to N times.

Designed to be invoked once and return a complete result. The LLM
in `diagnose` sees the previous fix and its result on retry so it
can self-correct (propose a different approach if the first fix
didn't work).
"""

import json
import subprocess
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI

from langgraph.graph import END, START, StateGraph
from src.k8s import core_api, pod_logs, recent_events


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


def check_cluster(state: K8sState) -> dict:
    v1 = core_api()
    issues = []

    pods = v1.list_pod_for_all_namespaces(watch=False)
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in (
                "CrashLoopBackOff",
                "Error",
                "ImagePullBackOff",
            ):
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,
                        "message": c.state.waiting.message or "",
                    }
                )
            if c.restart_count > 3:
                issues.append(
                    {
                        "kind": "pod_restart",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "restart_count": c.restart_count,
                    }
                )

    events = v1.list_event_for_all_namespaces(watch=False)
    for ev in events.items:
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

    return {"cluster_issues": issues[:20]}


def _gather_context(issues: list[dict]) -> tuple[dict, list[dict]]:
    """Pull logs for top problem pods and recent cluster events."""
    problem_pods = [i for i in issues if i.get("kind") == "pod"][:3]
    logs: dict[str, str] = {}
    for issue in problem_pods:
        key = f"{issue['namespace']}/{issue['name']}"
        try:
            logs[key] = pod_logs(issue["name"], issue["namespace"], tail=50, container="")
        except Exception as e:  # noqa: BLE001
            logs[key] = f"(failed to get logs: {e})"
    events = recent_events(namespace="", limit=20)
    return logs, events


def diagnose(state: K8sState) -> dict:
    if not state["cluster_issues"]:
        return {"diagnosis": "No issues found", "decision": "done"}

    logs, events = _gather_context(state["cluster_issues"])

    history = ""
    if state.get("proposed_fix"):
        history = (
            f"\nPrevious fix attempt: {state['proposed_fix']}\n"
            f"Previous fix result: {state.get('fix_result', '(none)')}\n"
            f"Previous diagnosis: {state.get('diagnosis', '(none)')}\n"
            "If the previous fix did not work, propose a DIFFERENT approach.\n"
        )

    prompt = (
        "You are a Kubernetes SRE. Investigate the cluster and propose a fix.\n\n"
        f"User task: {state.get('task', 'diagnose and fix cluster issues')}\n\n"
        f"Cluster issues:\n{json.dumps(state['cluster_issues'], indent=2)}\n\n"
        f"Recent logs for problem pods:\n{json.dumps(logs, indent=2)}\n\n"
        f"Recent cluster events:\n{json.dumps(events, indent=2)}\n"
        f"{history}\n"
        'Reply as JSON: {"diagnosis": "...", "proposed_fix": "kubectl ..."}'
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    rsp = llm.invoke(prompt)
    try:
        data = json.loads(rsp.content)
    except json.JSONDecodeError:
        data = {"diagnosis": rsp.content, "proposed_fix": ""}

    return {
        "diagnosis": data.get("diagnosis", ""),
        "proposed_fix": data.get("proposed_fix", ""),
        "decision": "fix",
    }


def attempt_fix(state: K8sState) -> dict:
    if not state["proposed_fix"]:
        return {"fix_result": "No fix proposed", "decision": "failed"}

    result = subprocess.run(
        state["proposed_fix"],
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {"fix_result": result.stdout + result.stderr}


def verify_fix(state: K8sState) -> dict:
    v1 = core_api()
    pods = v1.list_pod_for_all_namespaces(watch=False)
    still_issues = False
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in (
                "CrashLoopBackOff",
                "Error",
                "ImagePullBackOff",
            ):
                still_issues = True
                break

    verified = not still_issues
    update: dict = {"verified": verified}
    if not verified:
        update["retry_count"] = state.get("retry_count", 0) + 1
    return update


def decide(state: K8sState) -> Literal["done", "retry"]:
    if state["verified"]:
        return "done"
    if state.get("retry_count", 0) < state.get("max_retries", 3):
        return "retry"
    return "done"


graph = (
    StateGraph(K8sState)
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
    .compile()
)

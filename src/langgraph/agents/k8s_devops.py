"""K8s DevOps LangGraph: check, diagnose, fix, verify, retry up to N times."""

import json
import os
import subprocess
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr

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


def check_cluster(state: K8sState) -> dict:
    v1 = core_api()
    issues = []
    pods = v1.list_pod_for_all_namespaces(watch=False)
    for pod in pods.items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in (  # type: ignore[union-attr]
                "CrashLoopBackOff",
                "Error",
                "ImagePullBackOff",
            ):
                issues.append(
                    {
                        "kind": "pod",
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "reason": c.state.waiting.reason,  # type: ignore[union-attr]
                        "message": c.state.waiting.message or "",  # type: ignore[union-attr]
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
    return {"cluster_issues": issues[:20]}


def _gather_context(issues: list[dict]) -> tuple[dict, list[dict]]:
    problem_pods = [i for i in issues if i.get("kind") == "pod"][:3]
    logs: dict[str, str] = {}
    for issue in problem_pods:
        key = f"{issue['namespace']}/{issue['name']}"
        try:
            logs[key] = pod_logs(issue["name"], issue["namespace"], tail=50)
        except Exception as e:  # noqa: BLE001
            logs[key] = f"(failed to get logs: {e})"
    return logs, recent_events(namespace="", limit=20)


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=SecretStr(os.environ["OPENAI_API_KEY"]) if "OPENAI_API_KEY" in os.environ else None,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        temperature=0,
    )


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

    rsp = _llm().invoke(prompt)
    try:
        content = rsp.content if isinstance(rsp.content, str) else str(rsp.content)
        data = json.loads(content)
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
        state["proposed_fix"], shell=True, capture_output=True, text=True, timeout=60
    )
    return {"fix_result": result.stdout + result.stderr}


def verify_fix(state: K8sState) -> dict:
    v1 = core_api()
    still_issues = False
    for pod in v1.list_pod_for_all_namespaces(watch=False).items:
        for c in pod.status.container_statuses or []:
            if c.state.waiting and c.state.waiting.reason in (  # type: ignore[union-attr]
                "CrashLoopBackOff",
                "Error",
                "ImagePullBackOff",
            ):
                still_issues = True
                break
    update: dict = {"verified": not still_issues}
    if not still_issues:
        update["retry_count"] = state.get("retry_count", 0) + 1
    return update


def decide(state: K8sState) -> Literal["done", "retry"]:
    if state["verified"]:
        return "done"
    if state.get("retry_count", 0) < state.get("max_retries", 3):
        return "retry"
    return "done"


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
    .compile()
)

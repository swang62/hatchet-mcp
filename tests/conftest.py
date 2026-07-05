"""Shared fixtures for integration tests (no external dependencies)."""

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.types import interrupt

from src.langgraph.agents.k8s_devops import K8sState, compile_graph, initial_state

load_dotenv()


# ── helpers ──


def make_mock_pod(name: str, namespace: str, reason: str, restart_count: int = 5):
    waiting = MagicMock()
    waiting.reason = reason
    waiting.message = f"mock {reason}"
    state = MagicMock()
    state.waiting = waiting
    state.running = None
    state.terminated = None
    cs = MagicMock()
    cs.name = f"{name}-container"
    cs.state = state
    cs.restart_count = restart_count
    cs.ready = False
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.status.container_statuses = [cs]
    pod.status.phase = "Running"
    return pod


def make_mock_deployment(name: str, namespace: str, ready: int, desired: int):
    d = MagicMock()
    d.metadata.name = name
    d.metadata.namespace = namespace
    d.spec.replicas = desired
    d.status.ready_replicas = ready
    return d


# ── fixtures ──


@pytest.fixture
def thread_id() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def checkpointer():
    return MemorySaver()


@pytest.fixture
def graph(checkpointer):
    return compile_graph(checkpointer)


@pytest.fixture
def base_config(thread_id):
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}


@pytest.fixture
def llm_marker(request):
    if "OPENAI_API_KEY" not in os.environ:
        pytest.skip("OPENAI_API_KEY not set — skipping LLM-dependent test")


# ── K8s mock factories ──


def k8s_mock_first_issue():
    call_count = [0]

    def list_pods(*_a, **_kw):
        call_count[0] += 1
        if call_count[0] == 1:
            items = [make_mock_pod("nginx-7f9b", "default", "CrashLoopBackOff")]
        else:
            items = []
        r = MagicMock()
        r.items = items
        return r

    mv1 = MagicMock()
    mv1.list_pod_for_all_namespaces = list_pods
    mv1.list_node = MagicMock(return_value=MagicMock(items=[]))
    return mv1


def k8s_mock_always_clean():
    r = MagicMock()
    r.items = []

    mv1 = MagicMock()
    mv1.list_pod_for_all_namespaces.return_value = r
    mv1.list_node = MagicMock(return_value=MagicMock(items=[]))
    return mv1


def k8s_mock_always_failing():
    def list_pods(*_a, **_kw):
        items = [make_mock_pod("nginx-7f9b", "default", "CrashLoopBackOff")]
        r = MagicMock()
        r.items = items
        return r

    mv1 = MagicMock()
    mv1.list_pod_for_all_namespaces = list_pods
    mv1.list_node = MagicMock(return_value=MagicMock(items=[]))
    return mv1


@pytest.fixture
def mock_k8s():
    with (
        patch("src.langgraph.agents.inspection.core_api") as mock_core,
        patch("src.langgraph.agents.inspection.apps_api") as mock_apps,
        patch("src.langgraph.agents.inspection.pod_logs", return_value="mock logs"),
        patch("src.langgraph.agents.inspection.recent_events", return_value=[]),
    ):
        mock_core.return_value = k8s_mock_first_issue()
        mock_apps.return_value = MagicMock()
        mock_apps.return_value.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
        yield mock_core


@pytest.fixture
def mock_k8s_always_clean():
    with (
        patch("src.langgraph.agents.inspection.core_api") as mock_core,
        patch("src.langgraph.agents.inspection.apps_api") as mock_apps,
        patch("src.langgraph.agents.inspection.pod_logs", return_value="mock logs"),
        patch("src.langgraph.agents.inspection.recent_events", return_value=[]),
    ):
        mock_core.return_value = k8s_mock_always_clean()
        mock_apps.return_value = MagicMock()
        mock_apps.return_value.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
        yield mock_core


@pytest.fixture
def mock_k8s_always_failing():
    with (
        patch("src.langgraph.agents.inspection.core_api") as mock_core,
        patch("src.langgraph.agents.inspection.apps_api") as mock_apps,
        patch("src.langgraph.agents.inspection.pod_logs", return_value="mock logs"),
        patch("src.langgraph.agents.inspection.recent_events", return_value=[]),
    ):
        mock_core.return_value = k8s_mock_always_failing()
        mock_apps.return_value = MagicMock()
        mock_apps.return_value.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
        yield mock_core


@pytest.fixture
def mock_subprocess():
    with patch.object(__import__("subprocess"), "run") as mock_run:
        mr = MagicMock()
        mr.stdout = "pod nginx-7f9b deleted"
        mr.stderr = ""
        mock_run.return_value = mr
        yield mock_run


# ── Minimal subgraph for testing interrupt/resume without LLM ──


def _build_interrupt_subgraph(checkpointer):
    def attempt_only(state: dict) -> dict:
        proposed = state.get("proposed_fix", "").strip()
        if not proposed:
            return {"fix_result": "No fix proposed", "fix_failed": True}
        inp = interrupt(
            {
                "proposed_fix": proposed,
                "diagnosis": state.get("diagnosis", ""),
                "summary": "E2E test",
            }
        )
        if not inp.get("approved"):
            return {"fix_result": "Rejected by human", "rejected": True}
        command = inp.get("command_override", proposed)
        return {"fix_result": f"Executed: {command}"}

    return (
        StateGraph(dict)
        .add_node("approve_fix", attempt_only)
        .add_edge(START, "approve_fix")
        .compile(checkpointer=checkpointer)
    )


@pytest.fixture
def interrupt_subgraph(checkpointer):
    return _build_interrupt_subgraph(checkpointer)


# ── State builder helpers ──


def fix_state(proposed_fix: str = "kubectl delete pod nginx-7f9b -n default") -> K8sState:
    s = initial_state("E2E test")
    s["cluster_issues"] = [
        {"kind": "pod", "name": "nginx-7f9b", "namespace": "default", "reason": "CrashLoopBackOff"}
    ]
    s["diagnosis"] = "nginx crash-looping"
    s["proposed_fix"] = proposed_fix
    return s

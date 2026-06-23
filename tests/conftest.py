"""Shared fixtures for E2E integration tests."""

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv
from langgraph.graph import START, StateGraph
from langgraph.types import interrupt

from src.langgraph.agents.k8s_devops import K8sState, _initial_state, compile_graph
from src.shared.checkpointer import get_checkpointer, setup_checkpointer_tables

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


# ── fixtures ──


@pytest.fixture(scope="session", autouse=True)
def _ensure_db():
    """Ensure checkpointer tables exist once per session."""
    setup_checkpointer_tables()


@pytest.fixture
def thread_id() -> str:
    """Unique thread ID per test."""
    return f"e2e-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _cleanup_threads(request):
    """Delete ALL threads before each test (clean slate)."""
    import psycopg

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        yield
        return
    with psycopg.connect(database_url, autocommit=True) as conn:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            conn.execute(f"DELETE FROM {table}")
    yield


@pytest.fixture
def checkpointer():
    with get_checkpointer() as cp:
        yield cp


@pytest.fixture
def graph(checkpointer):
    return compile_graph(checkpointer)


@pytest.fixture
def base_config(thread_id):
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}


@pytest.fixture
def llm_marker(request):
    """Skip test if no LLM configured (for tests needing real LLM calls)."""
    if "OPENAI_API_KEY" not in os.environ:
        pytest.skip("OPENAI_API_KEY not set — skipping LLM-dependent test")


# ── K8s mock factories ──


def k8s_mock_first_issue():
    """First list_pods call returns CrashLoopBackOff pod, subsequent return clean."""
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

    def list_events(*_a, **_kw):
        r = MagicMock()
        r.items = []
        return r

    mv1 = MagicMock()
    mv1.list_pod_for_all_namespaces = list_pods
    mv1.list_event_for_all_namespaces = list_events
    return mv1


def k8s_mock_always_clean():
    """list_pods always returns empty (no issues)."""
    r = MagicMock()
    r.items = []

    mv1 = MagicMock()
    mv1.list_pod_for_all_namespaces.return_value = r
    mv1.list_event_for_all_namespaces.return_value = r
    return mv1


def k8s_mock_always_failing():
    """list_pods always returns a CrashLoopBackOff pod (fix never works)."""

    def list_pods(*_a, **_kw):
        items = [make_mock_pod("nginx-7f9b", "default", "CrashLoopBackOff")]
        r = MagicMock()
        r.items = items
        return r

    mv1 = MagicMock()
    mv1.list_pod_for_all_namespaces = list_pods
    mv1.list_event_for_all_namespaces = lambda *a, **kw: MagicMock(items=[])
    return mv1


@pytest.fixture
def mock_k8s():
    """Patch core_api to return CrashLoopBackOff on first call, clean afterwards."""
    with patch("src.langgraph.agents.k8s_devops.core_api") as mock_core:
        mock_core.return_value = k8s_mock_first_issue()
        yield mock_core


@pytest.fixture
def mock_k8s_always_clean():
    """Patch core_api to always return clean cluster."""
    with patch("src.langgraph.agents.k8s_devops.core_api") as mock_core:
        mock_core.return_value = k8s_mock_always_clean()
        yield mock_core


@pytest.fixture
def mock_k8s_always_failing():
    """Patch core_api to always return failing pod."""
    with patch("src.langgraph.agents.k8s_devops.core_api") as mock_core:
        mock_core.return_value = k8s_mock_always_failing()
        yield mock_core


@pytest.fixture
def mock_subprocess():
    """Patch subprocess.run to return success."""
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
            return {
                "fix_result": "No fix proposed",
                "decision": "failed",
                "retry_count": state.get("retry_count", 0) + 1,
            }
        inp = interrupt(
            {
                "proposed_fix": proposed,
                "diagnosis": state.get("diagnosis", ""),
                "summary": "E2E test",
            }
        )
        if not inp.get("approved"):
            return {"fix_result": "Rejected by human", "verified": False, "decision": "rejected"}
        command = inp.get("command_override", proposed)
        return {
            "fix_result": f"Executed: {command}",
            "verified": True,
            "retry_count": state.get("retry_count", 0) + 1,
        }

    return (
        StateGraph(dict)  # type: ignore[arg-type]
        .add_node("attempt_fix", attempt_only)  # type: ignore[arg-type]
        .add_edge(START, "attempt_fix")
        .compile(checkpointer=checkpointer)
    )


@pytest.fixture
def interrupt_subgraph(checkpointer):
    return _build_interrupt_subgraph(checkpointer)


# ── State builder helpers ──


def fix_state(proposed_fix: str = "kubectl delete pod nginx-7f9b -n default") -> K8sState:
    s = _initial_state("E2E test")
    s["cluster_issues"] = [
        {"kind": "pod", "name": "nginx-7f9b", "namespace": "default", "reason": "CrashLoopBackOff"}
    ]
    s["diagnosis"] = "nginx crash-looping"
    s["proposed_fix"] = proposed_fix
    s["decision"] = "fix"
    return s

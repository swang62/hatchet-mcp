from typing import Any

from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.shared.constants import K8S_MAX_RETRIES
from src.shared.types import K8sState
from src.shared.utils import trunc

from .nodes import approve_fix, check_cluster, diagnose, execute_fix, wait_for_recovery


def _ctx(config: RunnableConfig | None) -> Any | None:
    if config is None:
        return None
    return config.get("configurable", {}).get("__ctx__")


def _logged_node(name: str, fn):
    def wrapped(state: K8sState, config: RunnableConfig | None = None, **kwargs) -> dict:
        c = _ctx(config)
        if c:
            c.log(
                f"[{name}] input: failed_retries={state.get('failed_retries', 0)}/{K8S_MAX_RETRIES} rejected={state.get('rejected', False)} issues={len(state.get('cluster_issues', []))}"
            )
        try:
            result = fn(state)
            if c:
                c.log(f"[{name}] output: {trunc(str(result))}")
            return result
        except Exception as e:
            if c:
                c.log(f"[{name}] error: {e}")
            raise

    return wrapped


def _build_graph() -> StateGraph:
    graph = (
        StateGraph(K8sState)
        .add_node("check_cluster", _logged_node("check_cluster", check_cluster))
        .add_node("diagnose", _logged_node("diagnose", diagnose))
        .add_node("approve_fix", _logged_node("approve_fix", approve_fix))
        .add_node("execute_fix", _logged_node("execute_fix", execute_fix))
        .add_node("wait_for_recovery", _logged_node("wait_for_recovery", wait_for_recovery))
        .add_conditional_edges(
            "check_cluster",
            lambda s: (
                "diagnose"
                if s.get("cluster_issues") and s.get("failed_retries", 0) < K8S_MAX_RETRIES
                else "done"
            ),
            {"diagnose": "diagnose", "done": END},
        )
        .add_edge("diagnose", "approve_fix")
        .add_conditional_edges(
            "approve_fix",
            lambda s: "rejected" if s.get("rejected") else "execute",
            {"rejected": END, "execute": "execute_fix"},
        )
        .add_edge("execute_fix", "wait_for_recovery")
        .add_edge("wait_for_recovery", "check_cluster")
        .add_edge(START, "check_cluster")
    )
    return graph


def compile_graph(checkpointer=None) -> CompiledStateGraph:
    return _build_graph().compile(checkpointer=checkpointer)

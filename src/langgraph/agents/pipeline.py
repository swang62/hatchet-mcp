from typing import Any

from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.shared.constants import DEVOPS_MAX_RETRIES

from .inspection import check_cluster
from .operations import approve_fix, decide, diagnose, execute_fix, verify_fix
from .schemas import K8sState


def _trunc(text: str, maxlen: int = 300) -> str:
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "..."


def _ctx(config: RunnableConfig | None) -> Any | None:
    if config is None:
        return None
    return config.get("configurable", {}).get("__ctx__")


def _logged_node(name: str, fn):
    def wrapped(state: K8sState, config: RunnableConfig | None = None, **kwargs) -> dict:
        c = _ctx(config)
        if c:
            c.log(
                f"[{name}] input: retry={state.get('retry_count', 0)}/{DEVOPS_MAX_RETRIES} rejected={state.get('rejected', False)} fix_failed={state.get('fix_failed', False)} issues={len(state.get('cluster_issues', []))}"
            )
        try:
            result = fn(state)
            if c:
                c.log(f"[{name}] output: {_trunc(str(result))}")
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
        .add_node("verify_fix", _logged_node("verify_fix", verify_fix))
        .add_conditional_edges(
            "check_cluster",
            lambda s: "diagnose" if s["cluster_issues"] else "done",
            {"diagnose": "diagnose", "done": END},
        )
        .add_edge("diagnose", "approve_fix")
        .add_edge("approve_fix", "execute_fix")
        .add_edge("execute_fix", "verify_fix")
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

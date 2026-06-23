"""Shared Postgres checkpointer for LangGraph HITL."""

import os
from contextlib import contextmanager

from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver


@contextmanager
def get_checkpointer():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL not set — required for checkpointer-based HITL")
    with PostgresSaver.from_conn_string(database_url) as cp:
        yield cp


def setup_checkpointer_tables() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return
    with PostgresSaver.from_conn_string(database_url) as cp:
        cp.setup()


def list_paused_threads() -> list[dict]:
    """List threads paused at an interrupt (waiting for human approval).

    Iterates checkpoint tuples via PostgresSaver.list(), deduplicates by
    thread_id, and filters to those with pending tasks (interrupted).
    Returns empty list if no DATABASE_URL.
    """
    from src.langgraph.agents.k8s_devops import compile_graph

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    with get_checkpointer() as cp:
        g = compile_graph(cp)
        for checkpoint_tuple in cp.list(None):
            configurable = checkpoint_tuple.config.get("configurable")
            if not configurable or "thread_id" not in configurable:
                continue
            tid = str(configurable["thread_id"])
            if tid in seen:
                continue
            seen.add(tid)
            config: RunnableConfig = {"configurable": {"thread_id": tid}}
            snapshot = g.get_state(config)
            if snapshot.next:
                results.append({"thread_id": tid})

    return results

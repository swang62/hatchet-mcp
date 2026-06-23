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

    Queries LangGraph-specific checkpoints (nested under `@` suffix) for
    threads with pending tasks. Returns empty list if no DATABASE_URL.
    """
    from src.langgraph.agents.k8s_devops import compile_graph

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return []

    import psycopg

    assert database_url
    with psycopg.connect(database_url) as conn:
        cur = conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id")
        raw_threads = cur.fetchall()

    if not raw_threads:
        return []

    results: list[dict] = []
    with get_checkpointer() as cp:
        g = compile_graph(cp)
        for (tid,) in raw_threads:
            config: RunnableConfig = {"configurable": {"thread_id": tid}}
            snapshot = g.get_state(config)
            if snapshot.next:
                results.append({"thread_id": tid})

    return results

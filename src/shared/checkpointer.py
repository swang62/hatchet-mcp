"""Shared Postgres checkpointer for LangGraph HITL."""

import os
from contextlib import contextmanager

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

    Queries the checkpoints table for thread_ids, then filters to only
    those where graph.get_state() shows pending tasks (interrupted).
    Returns empty list if no DATABASE_URL.
    """
    from src.langgraph.agents.k8s_devops import compile_graph

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return []

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:  # type: ignore[arg-type]
        thread_rows = conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()

    if not thread_rows:
        return []

    results: list[dict] = []
    with get_checkpointer() as cp:
        g = compile_graph(cp)
        for row in thread_rows:
            tid = row["thread_id"]  # type: ignore[index]
            config = {"configurable": {"thread_id": tid}}
            snapshot = g.get_state(config)  # type: ignore[arg-type]
            if snapshot.next:
                results.append({"thread_id": tid})

    return results

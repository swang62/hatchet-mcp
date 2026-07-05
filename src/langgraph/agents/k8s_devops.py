"""K8s DevOps LangGraph: check, diagnose, approve, execute, verify, retry.

Supports human-in-the-loop via interrupt() before every mutating fix.
Use compile_graph(checkpointer) to enable HITL; compile_graph() for auto mode.
"""

from src.langgraph.agents.pipeline import compile_graph
from src.langgraph.agents.schemas import K8sState, initial_state

__all__ = ["K8sState", "initial_state", "compile_graph", "graph"]

graph = compile_graph()

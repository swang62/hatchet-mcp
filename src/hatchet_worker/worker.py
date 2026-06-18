"""Hatchet worker: registers all LangGraph agents as durable tasks.

Run:
    just worker

Each workflow wraps a compiled LangGraph graph. Hatchet handles
durable execution, retries, event triggers, and dashboard visibility.
"""

from hatchet_sdk import Hatchet

from src.hatchet_worker.workflows.k8s_devops import run_k8s_check
from src.hatchet_worker.workflows.knowledge_ingestion import run_ingestion

hatchet = Hatchet(debug=True)


kb_workflow = hatchet.workflow(
    name="knowledge_ingestion",
    on_events=["kb:ingest"],
)


@kb_workflow.task(name="ingest")
def ingest_task(input: dict, ctx) -> dict:
    return run_ingestion(input, ctx)


k8s_workflow = hatchet.workflow(
    name="k8s_devops",
    on_events=["kb:k8s:monitor"],
)


@k8s_workflow.task(name="monitor")
def monitor_task(input: dict, ctx) -> dict:
    return run_k8s_check(input, ctx)


def main():
    worker = hatchet.worker("hatchet-mcp-worker", max_runs=10)
    worker.start()


if __name__ == "__main__":
    main()

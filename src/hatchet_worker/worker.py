"""Hatchet worker: registers LangGraph agents as durable tasks."""

from dotenv import load_dotenv
from hatchet_sdk import Context, Hatchet
from hatchet_sdk.opentelemetry.instrumentor import HatchetInstrumentor

from src.hatchet_worker.models import K8sDevOpsInput, K8sToolInput, KnowledgeIngestionInput
from src.hatchet_worker.workflows.k8s_devops import run_k8s_check
from src.hatchet_worker.workflows.k8s_tool import run_k8s_tool
from src.hatchet_worker.workflows.knowledge_ingestion import register_tasks

HatchetInstrumentor().instrument()
load_dotenv()
hatchet = Hatchet()

# Knowledge Ingestion (4 tasks for per-step dashboard visibility)
kb_workflow = hatchet.workflow(
    name="knowledge_ingestion",
    input_validator=KnowledgeIngestionInput,
    on_events=["ingest:document"],
)
register_tasks(kb_workflow)

# K8s DevOps Agent (event-triggered, long-running)
k8s_workflow = hatchet.workflow(
    name="k8s_devops",
    input_validator=K8sDevOpsInput,
    on_events=["k8s:devops"],
)


@k8s_workflow.task(name="agent")
def agent_task(input: K8sDevOpsInput, ctx: Context) -> dict:
    return run_k8s_check(input, ctx)


# K8s Tools (triggered synchronously)
k8s_tool_workflow = hatchet.workflow(
    name="k8s_tool",
    input_validator=K8sToolInput,
)


@k8s_tool_workflow.task(name="execute")
def tool_task(input: K8sToolInput, ctx: Context) -> dict:
    return run_k8s_tool(input, ctx)


def main():
    worker = hatchet.worker(
        "hatchet-mcp-worker",
        slots=4,
        workflows=[kb_workflow, k8s_workflow, k8s_tool_workflow],
    )
    worker.start()


if __name__ == "__main__":
    main()

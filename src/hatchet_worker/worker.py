"""Hatchet worker: registers LangGraph agents as durable tasks."""

from dotenv import load_dotenv
from hatchet_sdk import Context, Hatchet
from hatchet_sdk.opentelemetry.instrumentor import HatchetInstrumentor

from src.hatchet_worker.models import (
    K8sDevOpsInput,
    K8sDevOpsResumeInput,
    K8sToolInput,
    KnowledgeIngestionInput,
)
from src.hatchet_worker.workflows.k8s_devops import run_k8s_check
from src.hatchet_worker.workflows.k8s_devops_resume import run_k8s_resume
from src.hatchet_worker.workflows.k8s_tool import run_k8s_tool
from src.hatchet_worker.workflows.knowledge_ingestion import run_kb_ingestion
from src.shared.checkpointer import setup_checkpointer_tables
from src.shared.constants import INGEST_EVENT, WORKER_NAME, WORKER_SLOTS

HatchetInstrumentor().instrument()
load_dotenv()
hatchet = Hatchet()

# Ensure Postgres checkpoint tables exist for HITL
try:
    setup_checkpointer_tables()
except Exception:
    pass  # HITL unavailable if no DATABASE_URL, non-fatal

# Knowledge Ingestion
kb_workflow = hatchet.workflow(
    name="knowledge_ingestion",
    input_validator=KnowledgeIngestionInput,
    on_events=[INGEST_EVENT],
)


@kb_workflow.task(name="ingest")
def kb_task(input: KnowledgeIngestionInput, ctx: Context) -> dict:
    return run_kb_ingestion(input, ctx)


# K8s DevOps Agent (triggered via runs.create() from MCP for HITL)
k8s_workflow = hatchet.workflow(
    name="k8s_devops",
    input_validator=K8sDevOpsInput,
)


@k8s_workflow.task(name="agent")
def agent_task(input: K8sDevOpsInput, ctx: Context) -> dict:
    return run_k8s_check(input, ctx)


# K8s DevOps Resume (triggered via runs.create() from MCP)
k8s_resume_workflow = hatchet.workflow(
    name="k8s_devops_resume",
    input_validator=K8sDevOpsResumeInput,
)


@k8s_resume_workflow.task(name="resume")
def resume_task(input: K8sDevOpsResumeInput, ctx: Context) -> dict:
    return run_k8s_resume(input, ctx)


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
        WORKER_NAME,
        slots=WORKER_SLOTS,
        workflows=[kb_workflow, k8s_workflow, k8s_resume_workflow, k8s_tool_workflow],
    )
    worker.start()


if __name__ == "__main__":
    main()

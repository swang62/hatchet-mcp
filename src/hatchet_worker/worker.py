"""Hatchet worker: registers LangGraph agents as durable tasks."""

from dotenv import load_dotenv
from hatchet_sdk import Context, Hatchet
from hatchet_sdk.opentelemetry.instrumentor import HatchetInstrumentor

from src.hatchet_worker.workflows.k8s_check import k8s_check
from src.hatchet_worker.workflows.k8s_resume import k8s_resume
from src.hatchet_worker.workflows.k8s_tools import k8s_tools
from src.shared.checkpointer import setup_checkpointer_tables
from src.shared.constants import (
    K8S_DEVOPS_WORKFLOW,
    K8S_RESUME_WORKFLOW,
    K8S_TOOL_WORKFLOW,
    WORKER_NAME,
    WORKER_SLOTS,
)
from src.shared.scheduling import register_nightly_cron
from src.shared.types import K8sDevOpsInput, K8sResumeInput, K8sToolInput

HatchetInstrumentor().instrument()
load_dotenv()
hatchet = Hatchet()

# Ensure Postgres checkpoint tables exist for HITL
try:
    setup_checkpointer_tables()
except Exception:
    raise RuntimeError(
        "Failed to setup checkpointer tables. Ensure Postgres is running and accessible."
    )

# Register nightly health check cron (idempotent)
register_nightly_cron(hatchet)

# ── K8s DevOps Agent ──

k8s_check_workflow = hatchet.workflow(
    name=K8S_DEVOPS_WORKFLOW,
    input_validator=K8sDevOpsInput,
)


@k8s_check_workflow.task(name="agent")
def agent_task(input: K8sDevOpsInput, ctx: Context) -> dict:
    return k8s_check(input, ctx)


# ── K8s DevOps Resume ──

k8s_resume_workflow = hatchet.workflow(
    name=K8S_RESUME_WORKFLOW,
    input_validator=K8sResumeInput,
)


@k8s_resume_workflow.task(name="resume")
def resume_task(input: K8sResumeInput, ctx: Context) -> dict:
    return k8s_resume(input, ctx)


# ── K8s Tools ──

k8s_tools_workflow = hatchet.workflow(
    name=K8S_TOOL_WORKFLOW,
    input_validator=K8sToolInput,
)


@k8s_tools_workflow.task(name="execute")
def tool_task(input: K8sToolInput, ctx: Context) -> dict:
    return k8s_tools(input, ctx)


# ── Main ──


def main():
    worker = hatchet.worker(
        WORKER_NAME,
        slots=WORKER_SLOTS,
        workflows=[k8s_check_workflow, k8s_resume_workflow, k8s_tools_workflow],
    )
    worker.start()


if __name__ == "__main__":
    main()

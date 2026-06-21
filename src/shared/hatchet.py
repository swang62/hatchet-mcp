"""Shared Hatchet client: lazy singleton + sync workflow runner."""

from __future__ import annotations

import concurrent.futures
from typing import Any

from hatchet_sdk import Hatchet

_hatchet: Hatchet | None = None


def get_hatchet() -> Hatchet:
    """Return the shared Hatchet client (lazy-init)."""
    global _hatchet  # noqa: PLW0603
    if _hatchet is None:
        _hatchet = Hatchet()
    return _hatchet


def run_sync_workflow(
    workflow_name: str,
    input_data: dict[str, Any],
    task_name: str = "execute",
    timeout: int = 60,
) -> dict[str, Any]:
    """Run a Hatchet workflow via the REST API and wait for the result."""
    hatchet = get_hatchet()
    details = hatchet.runs.create(workflow_name, input_data)
    ref = hatchet.runs.get_run_ref(details.run.metadata.id)

    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(ref.result)
        try:
            completed = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return {
                "error": (
                    f"Workflow {workflow_name} (run {details.run.metadata.id}) "
                    f"did not complete within {timeout}s. Is the worker running?"
                ),
                "workflow_run_id": details.run.metadata.id,
                "status": "timeout",
            }

    task_output = completed.get(task_name, completed)
    if isinstance(task_output, dict) and "error" in task_output:
        return task_output
    return task_output

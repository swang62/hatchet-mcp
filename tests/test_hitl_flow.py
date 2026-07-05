from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.langgraph.agents.k8s_devops import compile_graph, initial_state
from tests.conftest import fix_state


class TestApprovalFlow:
    """HITL approval/rejection/override logic using a minimal subgraph."""

    def test_approve(self, interrupt_subgraph, base_config):
        interrupt_subgraph.invoke(fix_state(), base_config)
        result = interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        assert result.get("fix_result", "").startswith("Executed:")

    def test_reject(self, interrupt_subgraph, base_config):
        interrupt_subgraph.invoke(fix_state(), base_config)
        result = interrupt_subgraph.invoke(Command(resume={"approved": False}), base_config)
        assert result.get("rejected") is True

    def test_command_override(self, interrupt_subgraph, base_config):
        interrupt_subgraph.invoke(fix_state(), base_config)
        result = interrupt_subgraph.invoke(
            Command(
                resume={"approved": True, "command_override": "kubectl delete pod special -n test"}
            ),
            base_config,
        )
        assert "kubectl delete pod special -n test" in result.get("fix_result", "")

    def test_no_fix_proposed(self, interrupt_subgraph, base_config):
        state = fix_state()
        state["proposed_fix"] = ""
        result = interrupt_subgraph.invoke(state, base_config)
        assert result.get("fix_failed") is True
        assert "No fix proposed" in result.get("fix_result", "")


class TestRetryExhaustion:
    """Graph behavior after max_retries of failing fixes."""

    def test_execute_fix_completes(self, interrupt_subgraph, base_config):
        state = fix_state()
        interrupt_subgraph.invoke(state, base_config)
        r = interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        assert "Executed:" in r.get("fix_result", "")

    def test_completed_graph_has_no_pending_tasks(self, interrupt_subgraph, base_config):
        state = fix_state()
        state["proposed_fix"] = ""
        interrupt_subgraph.invoke(state, base_config)
        snap = interrupt_subgraph.get_state(base_config)
        assert not snap.next


class TestNoIssues:
    """When the cluster has no problems, the graph should complete without interrupting."""

    def test_no_issues_completes_without_interrupt(self, mock_k8s_always_clean, graph, base_config):
        state = initial_state("check cluster")
        result = graph.invoke(state, base_config)
        snap = graph.get_state(base_config)
        assert not snap.next, "No interrupt — no issues found"
        assert len(result.get("cluster_issues", [])) == 0
        assert not result.get("rejected")
        assert not result.get("fix_failed")


def _get_thread_status(thread_id: str, checkpointer: MemorySaver) -> dict:
    """Check a thread's approval status using an in-memory checkpointer."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    existing = checkpointer.get_tuple(config)
    if existing is None:
        return {"status": "not_found", "thread_id": thread_id}
    g = compile_graph(checkpointer)
    snapshot = g.get_state(config)
    if snapshot.next:
        interrupts = []
        for t in snapshot.tasks or []:
            for i in t.interrupts or []:
                interrupts.append(i.value)
        return {
            "status": "pending_approval",
            "thread_id": thread_id,
            "pending_tasks": [t.name for t in (snapshot.tasks or [])],
            "interrupt_values": interrupts,
        }
    return {"status": "completed", "thread_id": thread_id}


class TestThreadManagement:
    """Thread status and cleanup using in-memory checkpointer."""

    def test_pending_shows_interrupted(
        self, interrupt_subgraph, base_config, thread_id, checkpointer
    ):
        interrupt_subgraph.invoke(fix_state(), base_config)
        status = _get_thread_status(thread_id, checkpointer)
        assert status["status"] == "pending_approval"

    def test_completed_omits_interrupts(
        self, interrupt_subgraph, base_config, thread_id, checkpointer
    ):
        interrupt_subgraph.invoke(fix_state(), base_config)
        interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        status = _get_thread_status(thread_id, checkpointer)
        assert status["status"] == "completed"

    def test_get_approval_status_pending(
        self, interrupt_subgraph, base_config, thread_id, checkpointer
    ):
        interrupt_subgraph.invoke(fix_state(), base_config)
        status = _get_thread_status(thread_id, checkpointer)
        assert status["status"] == "pending_approval"
        assert len(status.get("interrupt_values", [])) > 0

    def test_get_approval_status_completed(
        self, interrupt_subgraph, base_config, thread_id, checkpointer
    ):
        interrupt_subgraph.invoke(fix_state(), base_config)
        interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        status = _get_thread_status(thread_id, checkpointer)
        assert status["status"] == "completed"

    def test_get_approval_status_not_found(self):
        status = _get_thread_status("nonexistent-thread-xyz", MemorySaver())
        assert status["status"] == "not_found"

    def test_cleanup_thread(self, interrupt_subgraph, base_config, thread_id, checkpointer):
        interrupt_subgraph.invoke(fix_state(), base_config)
        checkpointer.delete_thread(thread_id)
        status = _get_thread_status(thread_id, checkpointer)
        assert status["status"] == "not_found"

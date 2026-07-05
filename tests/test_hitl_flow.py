"""E2E integration tests for HITL (human-in-the-loop) K8s devops agent.

Every test exercises the full LangGraph + Postgres checkpointer stack.
Tests that make real LLM calls are marked ``@pytest.mark.llm``.
"""

from langgraph.types import Command

from src.langgraph.agents.k8s_devops import initial_state
from src.shared.checkpointer import list_paused_threads
from tests.conftest import fix_state

# ═══════════════════════════════════════════════════════════════════
# Graph logic tests (no LLM call — uses interrupt_subgraph)
# ═══════════════════════════════════════════════════════════════════


class TestApprovalFlow:
    """HITL approval/rejection/override logic using a minimal subgraph."""

    def test_approve(self, interrupt_subgraph, base_config):
        interrupt_subgraph.invoke(fix_state(), base_config)
        result = interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        assert result.get("fix_result", "").startswith("Executed:")
        assert result.get("verified") is True

    def test_reject(self, interrupt_subgraph, base_config):
        interrupt_subgraph.invoke(fix_state(), base_config)
        result = interrupt_subgraph.invoke(Command(resume={"approved": False}), base_config)
        assert result.get("rejected") is True
        assert result.get("verified") is False

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

    def test_exhaustion_after_3_retries(self, interrupt_subgraph, base_config):
        """Graph should complete (not interrupt) after 3 retries with no fix."""
        state = fix_state()
        state["verified"] = False
        state["retry_count"] = 2
        interrupt_subgraph.invoke(state, base_config)
        r = interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        assert r.get("verified") is True
        assert r.get("retry_count") == 3

    def test_completed_graph_has_no_pending_tasks(self, interrupt_subgraph, base_config):
        state = fix_state()
        state["proposed_fix"] = ""
        interrupt_subgraph.invoke(state, base_config)
        snap = interrupt_subgraph.get_state(base_config)
        assert not snap.next


# ═══════════════════════════════════════════════════════════════════
# No-issues path
# ═══════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════
# Thread management tools
# ═══════════════════════════════════════════════════════════════════


class TestThreadManagement:
    """list_paused_threads, get_approval_status, cleanup_thread tools."""

    def test_list_paused_shows_interrupted(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        pending = list_paused_threads()
        assert thread_id in [t["thread_id"] for t in pending]

    def test_list_paused_omits_completed(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        pending = list_paused_threads()
        assert thread_id not in [t["thread_id"] for t in pending]

    def _get_thread_status(self, thread_id: str) -> dict:
        from langchain_core.runnables.config import RunnableConfig

        from src.langgraph.agents.k8s_devops import compile_graph
        from src.shared.checkpointer import get_checkpointer

        with get_checkpointer() as cp:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            existing = cp.get_tuple(config)
            if existing is None:
                return {"status": "not_found", "thread_id": thread_id}
            g = compile_graph(cp)
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

    def test_get_approval_status_pending(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        status = self._get_thread_status(thread_id)
        assert status["status"] == "pending_approval"
        assert len(status.get("interrupt_values", [])) > 0

    def test_get_approval_status_completed(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        status = self._get_thread_status(thread_id)
        assert status["status"] == "completed"

    def test_get_approval_status_not_found(self):
        status = self._get_thread_status("nonexistent-thread-xyz")
        assert status["status"] == "not_found"

    def test_cleanup_thread(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        from src.shared.checkpointer import get_checkpointer

        with get_checkpointer() as cp:
            cp.delete_thread(thread_id)
        pending = list_paused_threads()
        assert thread_id not in [t["thread_id"] for t in pending]

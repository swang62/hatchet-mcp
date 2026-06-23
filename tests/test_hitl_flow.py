"""E2E integration tests for HITL (human-in-the-loop) K8s devops agent.

Every test exercises the full LangGraph + Postgres checkpointer stack.
Tests that make real LLM calls are marked ``@pytest.mark.llm``.
"""

import pytest
from langgraph.types import Command

from src.langgraph.agents.k8s_devops import _initial_state
from src.shared.checkpointer import list_paused_threads
from tests.conftest import fix_state

# ═══════════════════════════════════════════════════════════════════
# Full flow (requires real LLM call)
# ═══════════════════════════════════════════════════════════════════


class TestFullFlow:
    """Tests that run the complete graph including the LLM diagnosis node."""

    @pytest.mark.llm
    @pytest.mark.timeout(300)
    def test_interrupt_and_resume(self, mock_k8s, mock_subprocess, graph, base_config):
        """Full flow: detect issue → LLM diagnoses → interrupt → human approves → fix runs → verified."""
        state = _initial_state("fix nginx crash loop in default namespace")
        result = graph.invoke(state, base_config)
        snap = graph.get_state(base_config)

        assert snap.next, "Graph should be interrupted at attempt_fix"
        assert "attempt_fix" in snap.next

        issues = result.get("cluster_issues", [])
        assert len(issues) > 0

        diagnosis = result.get("diagnosis", "")
        assert len(diagnosis) > 20

        # Extract proposed_fix from interrupt value
        proposed_fix = ""
        for t in snap.tasks:
            for i in t.interrupts or []:
                proposed_fix = i.value.get("proposed_fix", "")
                val = i.value
                assert "diagnosis" in val
                assert "proposed_fix" in val
                assert "summary" in val
        assert proposed_fix, "interrupt should contain proposed_fix"
        assert "kubectl" in proposed_fix.lower(), (
            f"proposed_fix should be kubectl, got: {proposed_fix[:60]}"
        )

        # Resume with approval
        result2 = graph.invoke(Command(resume={"approved": True}), base_config)
        snap2 = graph.get_state(base_config)

        retries = 0
        while snap2.next and retries < 3:
            result2 = graph.invoke(Command(resume={"approved": True}), base_config)
            snap2 = graph.get_state(base_config)
            retries += 1

        assert not snap2.next, "Graph should have completed"
        assert result2.get("verified", False), "Fix should be verified"
        assert mock_subprocess.called, "subprocess.run should have been called"


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
        assert result.get("decision") == "rejected"
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
        assert result.get("decision") == "failed"
        assert "No fix proposed" in result.get("fix_result", "")


class TestRetryExhaustion:
    """Graph behavior after max_retries of failing fixes."""

    def test_exhaustion_after_3_retries(self, interrupt_subgraph, base_config):
        """Graph should complete (not interrupt) after 3 retries with no fix."""
        state = fix_state()
        state["verified"] = False
        state["retry_count"] = 2
        state["max_retries"] = 3
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
        state = _initial_state("check cluster")
        result = graph.invoke(state, base_config)
        snap = graph.get_state(base_config)
        assert not snap.next, "No interrupt — no issues found"
        assert len(result.get("cluster_issues", [])) == 0
        assert result.get("decision") == ""


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

    def test_get_approval_status_pending(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        from src.mcp.k8s_server import get_approval_status

        status = get_approval_status(thread_id)
        assert status["status"] == "pending_approval"
        assert len(status.get("interrupt_values", [])) > 0

    def test_get_approval_status_completed(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        interrupt_subgraph.invoke(Command(resume={"approved": True}), base_config)
        from src.mcp.k8s_server import get_approval_status

        status = get_approval_status(thread_id)
        assert status["status"] == "completed"

    def test_get_approval_status_not_found(self):
        from src.mcp.k8s_server import get_approval_status

        status = get_approval_status("nonexistent-thread-xyz")
        assert status["status"] == "not_found"

    def test_cleanup_thread(self, interrupt_subgraph, base_config, thread_id):
        interrupt_subgraph.invoke(fix_state(), base_config)
        from src.mcp.k8s_server import cleanup_thread

        result = cleanup_thread(thread_id)
        assert result["status"] == "deleted"
        pending = list_paused_threads()
        assert thread_id not in [t["thread_id"] for t in pending]

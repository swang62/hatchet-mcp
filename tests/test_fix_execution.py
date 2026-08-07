import subprocess
from unittest.mock import MagicMock, patch

from src.langgraph.agents.nodes import execute_fix
from src.shared.types import initial_state


def state_with_command(command: str):
    state = initial_state("test")
    state["proposed_fix"] = command
    return state


def test_execute_fix_skips_empty_command():
    with patch("src.langgraph.agents.nodes.subprocess.run") as run:
        assert execute_fix(state_with_command("")) == {"fix_result": ""}

    run.assert_not_called()


def test_execute_fix_returns_stdout_and_stderr():
    process = MagicMock(stdout="output\n", stderr="warning\n")
    with patch("src.langgraph.agents.nodes.subprocess.run", return_value=process) as run:
        assert execute_fix(state_with_command("kubectl get pods")) == {
            "fix_result": "output\nwarning\n"
        }

    run.assert_called_once_with(
        "kubectl get pods", shell=True, capture_output=True, text=True, timeout=10
    )


def test_execute_fix_reports_timeout():
    with patch(
        "src.langgraph.agents.nodes.subprocess.run",
        side_effect=subprocess.TimeoutExpired("kubectl get pods", 10),
    ):
        assert execute_fix(state_with_command("kubectl get pods")) == {
            "fix_result": "Command timed out after 10s"
        }

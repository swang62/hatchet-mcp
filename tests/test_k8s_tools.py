from unittest.mock import MagicMock, patch

from src.hatchet_worker.workflows.k8s_tools import k8s_tools
from src.shared.constants import K8S_EVENT_LIMIT, K8S_MAX_LOG_TAIL, K8S_TIMEOUT
from src.shared.enums import ToolName
from src.shared.types import K8sToolInput


def test_check_pods_forwards_namespace_and_restart_preference():
    ctx = MagicMock()
    with patch(
        "src.hatchet_worker.workflows.k8s_tools.list_problem_pods", return_value=[{"name": "api"}]
    ) as list_problem_pods:
        result = k8s_tools(
            K8sToolInput(
                tool=ToolName.CHECK_PODS,
                params={"namespace": "default", "include_restarts": False},
            ),
            ctx,
        )

    assert result == {"result": [{"name": "api"}]}
    list_problem_pods.assert_called_once_with("default", False)


def test_get_logs_uses_defaults_and_passes_container():
    ctx = MagicMock()
    with patch(
        "src.hatchet_worker.workflows.k8s_tools.pod_logs", return_value="recent logs"
    ) as pod_logs:
        result = k8s_tools(
            K8sToolInput(tool=ToolName.GET_LOGS, params={"pod": "api", "namespace": "default"}),
            ctx,
        )

    assert result == {"logs": "recent logs"}
    pod_logs.assert_called_once_with("api", "default", tail=K8S_MAX_LOG_TAIL, container="")


def test_debug_pod_collects_describe_logs_and_events():
    ctx = MagicMock()
    with (
        patch(
            "src.hatchet_worker.workflows.k8s_tools.describe_pod", return_value={"phase": "Running"}
        ),
        patch("src.hatchet_worker.workflows.k8s_tools.pod_logs", return_value="logs") as pod_logs,
        patch(
            "src.hatchet_worker.workflows.k8s_tools.recent_events",
            return_value=[{"reason": "BackOff"}],
        ) as events,
    ):
        result = k8s_tools(
            K8sToolInput(
                tool=ToolName.DEBUG_POD,
                params={"pod": "api", "namespace": "default", "tail": 10},
            ),
            ctx,
        )

    assert result == {
        "describe": {"phase": "Running"},
        "logs": "logs",
        "events": [{"reason": "BackOff"}],
    }
    pod_logs.assert_called_once_with("api", "default", tail=10, container="")
    events.assert_called_once_with("default", K8S_EVENT_LIMIT)


def test_exec_in_pod_forwards_custom_timeout():
    ctx = MagicMock()
    command_result = {"stdout": "ok", "stderr": "", "returncode": 0}
    with patch(
        "src.hatchet_worker.workflows.k8s_tools.exec_in_pod", return_value=command_result
    ) as exec_in_pod:
        result = k8s_tools(
            K8sToolInput(
                tool=ToolName.EXEC_IN_POD,
                params={"pod": "api", "namespace": "default", "command": "status", "timeout": 7},
            ),
            ctx,
        )

    assert result == command_result
    exec_in_pod.assert_called_once_with("api", "default", "status", 7)


def test_run_kubectl_uses_default_timeout():
    ctx = MagicMock()
    command_result = {"stdout": "ok", "stderr": "", "returncode": 0}
    with patch(
        "src.hatchet_worker.workflows.k8s_tools.run_kubectl", return_value=command_result
    ) as run_kubectl:
        result = k8s_tools(
            K8sToolInput(tool=ToolName.RUN_KUBECTL, params={"command": "kubectl get pods"}),
            ctx,
        )

    assert result == command_result
    run_kubectl.assert_called_once_with("kubectl get pods", K8S_TIMEOUT)


def test_unknown_tool_returns_error():
    ctx = MagicMock()
    input = K8sToolInput.model_construct(tool="unknown", params={})

    assert k8s_tools(input, ctx) == {"error": "Unknown tool: unknown"}

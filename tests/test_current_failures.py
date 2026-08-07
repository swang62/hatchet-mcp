from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.langgraph.agents import nodes
from src.langgraph.agents.inspect import check_pod_events
from src.shared.constants import K8S_RECENT_WINDOW_SECONDS
from src.shared.k8s import pod_logs, recent_events
from src.shared.types import initial_state


def test_check_cluster_ignores_historical_restart_counts():
    container = SimpleNamespace(
        ready=True,
        restart_count=99,
        state=SimpleNamespace(waiting=None, running=object()),
    )
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="healthy", namespace="default"),
        status=SimpleNamespace(container_statuses=[container]),
    )
    v1 = MagicMock()
    v1.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[pod])

    with (
        patch.object(nodes, "core_api", return_value=v1),
        patch.object(nodes, "check_pod_phase"),
        patch.object(nodes, "check_deployments"),
        patch.object(nodes, "check_nodes"),
        patch.object(
            nodes, "check_service_ingress_inventory", return_value={"missing_backends": []}
        ),
        patch.object(nodes, "recent_events", return_value=[]),
    ):
        assert nodes.check_cluster(initial_state("check cluster"))["cluster_issues"] == []


def test_recent_events_require_an_unhealthy_pod_and_current_timestamp():
    now = datetime.now(timezone.utc)
    unhealthy_pod = SimpleNamespace(
        metadata=SimpleNamespace(name="api", namespace="default"),
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(
                    state=SimpleNamespace(waiting=SimpleNamespace(reason="CrashLoopBackOff"))
                )
            ]
        ),
    )

    def event(timestamp):
        return SimpleNamespace(
            metadata=SimpleNamespace(name="api-event", namespace="default"),
            type="Warning",
            reason="BackOff",
            message="restart",
            count=1,
            last_timestamp=timestamp,
            involved_object=SimpleNamespace(kind="Pod", namespace="default", name="api"),
        )

    v1 = MagicMock()
    v1.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[unhealthy_pod])
    v1.list_node.return_value = SimpleNamespace(items=[])
    v1.list_event_for_all_namespaces.return_value = SimpleNamespace(
        items=[event(now), event(now - timedelta(seconds=K8S_RECENT_WINDOW_SECONDS + 1))]
    )

    with patch("src.shared.k8s.core_api", return_value=v1):
        assert recent_events() == [
            {
                "name": "api-event",
                "namespace": "default",
                "type": "Warning",
                "reason": "BackOff",
                "message": "restart",
                "count": 1,
                "last_seen": now.isoformat(),
            }
        ]


def test_pod_logs_are_limited_to_the_last_hour():
    v1 = MagicMock()
    v1.read_namespaced_pod_log.return_value = "recent log"

    with patch("src.shared.k8s.core_api", return_value=v1):
        assert pod_logs("api", "default") == "recent log"

    v1.read_namespaced_pod_log.assert_called_once_with(
        name="api",
        namespace="default",
        tail_lines=50,
        since_seconds=K8S_RECENT_WINDOW_SECONDS,
    )


def test_check_pod_events_ignores_stale_warnings():
    now = datetime.now(timezone.utc)
    pod = SimpleNamespace(metadata=SimpleNamespace(name="api", namespace="default"))

    def event(timestamp):
        return SimpleNamespace(
            type="Warning",
            reason="BackOff",
            message="restart",
            last_timestamp=timestamp,
        )

    v1 = MagicMock()
    v1.list_namespaced_event.return_value = SimpleNamespace(
        items=[event(now), event(now - timedelta(seconds=K8S_RECENT_WINDOW_SECONDS + 1))]
    )
    issues: list[dict] = []

    check_pod_events(v1, pod, issues)

    assert issues == [
        {
            "kind": "pod_event",
            "name": "api",
            "namespace": "default",
            "reason": "BackOff",
            "message": "restart",
        }
    ]

from kubernetes.client import models

class CoreV1Api:
    def __init__(self, api_client: object | None = None) -> None: ...
    def list_pod_for_all_namespaces(
        self,
        allow_watch_bookmarks: bool | None = None,
        _continue: str | None = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int | None = None,
        pretty: str | None = None,
        resource_version: str | None = None,
        resource_version_match: str | None = None,
        send_initial_events: bool | None = None,
        timeout_seconds: int | None = None,
        watch: bool | None = None,
    ) -> models.V1PodList: ...
    def list_namespaced_pod(
        self,
        namespace: str,
        allow_watch_bookmarks: bool | None = None,
        _continue: str | None = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int | None = None,
        pretty: str | None = None,
        resource_version: str | None = None,
        resource_version_match: str | None = None,
        send_initial_events: bool | None = None,
        timeout_seconds: int | None = None,
        watch: bool | None = None,
    ) -> models.V1PodList: ...
    def read_namespaced_pod(
        self,
        name: str,
        namespace: str,
        pretty: str | None = None,
    ) -> models.V1Pod: ...
    def read_namespaced_pod_log(
        self,
        name: str,
        namespace: str,
        container: str | None = None,
        follow: bool | None = None,
        insecure_skip_tls_verify_backend: bool | None = None,
        limit_bytes: int | None = None,
        pretty: str | None = None,
        previous: bool | None = None,
        since_seconds: int | None = None,
        tail_lines: int | None = None,
        timestamps: bool | None = None,
    ) -> str: ...
    def list_event_for_all_namespaces(
        self,
        allow_watch_bookmarks: bool | None = None,
        _continue: str | None = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int | None = None,
        pretty: str | None = None,
        resource_version: str | None = None,
        resource_version_match: str | None = None,
        send_initial_events: bool | None = None,
        timeout_seconds: int | None = None,
        watch: bool | None = None,
    ) -> models.CoreV1EventList: ...
    def list_namespaced_event(
        self,
        namespace: str,
        allow_watch_bookmarks: bool | None = None,
        _continue: str | None = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int | None = None,
        pretty: str | None = None,
        resource_version: str | None = None,
        resource_version_match: str | None = None,
        send_initial_events: bool | None = None,
        timeout_seconds: int | None = None,
        watch: bool | None = None,
    ) -> models.CoreV1EventList: ...

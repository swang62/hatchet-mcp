from enum import StrEnum


class InspectCommand(StrEnum):
    LIST = "list"
    DESCRIBE = "describe"
    LOGS = "logs"
    EVENTS = "events"
    EXEC = "exec"
    PROBLEM_PODS = "problem_pods"


class ResourceKind(StrEnum):
    PODS = "pods"
    DEPLOYMENTS = "deployments"
    STATEFULSETS = "statefulsets"
    DAEMONSETS = "daemonsets"
    SERVICES = "services"
    INGRESSES = "ingresses"
    CONFIGMAPS = "configmaps"
    SECRETS = "secrets"
    EVENTS = "events"


class ResumeAction(StrEnum):
    LIST = "list"
    STATUS = "status"
    APPROVE = "approve"
    REJECT = "reject"
    CLEANUP = "cleanup"


class ToolName(StrEnum):
    CHECK_PODS = "check_pods"
    GET_LOGS = "get_logs"
    DESCRIBE_POD = "describe_pod"
    GET_EVENTS = "get_events"
    DEBUG_POD = "debug_pod"
    RUN_KUBECTL = "run_kubectl"
    GET_DEPLOYMENTS = "get_deployments"
    GET_STATEFULSETS = "get_statefulsets"
    GET_DAEMONSETS = "get_daemonsets"
    GET_SERVICES = "get_services"
    GET_INGRESSES = "get_ingresses"
    GET_CONFIGMAPS = "get_configmaps"
    GET_SECRETS = "get_secrets"
    EXEC_IN_POD = "exec_in_pod"


class WorkflowStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    REJECTED = "rejected"
    MANUAL_INTERVENTION = "manual_intervention_needed"
    NOT_FOUND = "not_found"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    DELETED = "deleted"
    TIMEOUT = "timeout"

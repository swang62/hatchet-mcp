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

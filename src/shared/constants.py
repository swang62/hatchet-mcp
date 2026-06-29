from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── K8s ──
K8S_TIMEOUT = 300
K8S_DEFAULT_LOG_TAIL = 100
K8S_DEFAULT_EVENT_LIMIT = 50
K8S_CONTEXT_EVENT_LIMIT = 20
K8S_EVENT_FILTER_TYPES = {"Warning", "Error"}
K8S_RESTART_THRESHOLD = 3
K8S_MAX_ISSUES = 20
K8S_MAX_PROBLEM_PODS = 3
K8S_VERIFY_POLL_INTERVAL = 5
K8S_PENDING_THRESHOLD = 120
K8S_NOT_READY_THRESHOLD = 60
K8S_TOOL_WORKFLOW = "k8s_tool"
K8S_DEVOPS_WORKFLOW = "k8s_devops"
K8S_RESUME_WORKFLOW = "k8s_devops_resume"

K8S_FAILURE_REASONS: set[str] = {
    "CrashLoopBackOff",
    "Error",
    "ImagePullBackOff",
    "ErrImagePull",
    "ImagePullError",
    "CreateContainerConfigError",
    "CreateContainerError",
    "InvalidImageName",
    "RunContainerError",
}

# ── Worker ──
WORKER_NAME = "hatchet-mcp-worker"
WORKER_SLOTS = 4
DEFAULT_TASK_NAME = "execute"
WORKFLOW_TIMEOUT = K8S_TIMEOUT

# ── LLM / Model ──
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
LLM_TEMPERATURE = 0

# ── Logging ──
LOG_OUTPUT_MAX = 300
MCP_LOG_LEVEL = "WARNING"

# ── LangGraph ──
GRAPH_RECURSION_LIMIT = 50
DEVOPS_MAX_RETRIES = 3

# ── Misc ──
KUBECTL_CMD = "kubectl"

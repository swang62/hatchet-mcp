from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── K8s ──
K8S_EVENT_FILTER_TYPES = {"Warning", "Error"}
K8S_EVENT_LIMIT = 20
K8S_MAX_ISSUES = 20
K8S_MAX_LOG_TAIL = 50
K8S_MAX_PROBLEM_PODS = 3
K8S_MAX_RETRIES = 3
K8S_PENDING_THRESHOLD = 60
K8S_RESTART_THRESHOLD = 3
K8S_TIMEOUT = 60
K8S_EXEC_TIMEOUT = 5
K8S_API_TIMEOUT = 10
K8S_VERIFY_TIMEOUT = 20

K8S_TOOL_WORKFLOW = "k8s_tools"
K8S_DEVOPS_WORKFLOW = "k8s_check"
K8S_RESUME_WORKFLOW = "k8s_resume"

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
DEFAULT_TASK_NAME = "execute"
WORKER_NAME = "hatchet-mcp-worker"
WORKER_SLOTS = 4
WORKFLOW_TIMEOUT = K8S_TIMEOUT

# ── LLM / Model ──
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
LLM_TEMPERATURE = 0.3
LLM_SYSTEM_PROMPT = """You are an automated Kubernetes remediation system. Your goal is to restore the cluster to a fully healthy state.

You have the full picture of the cluster — current pod states, events, and logs.
Analyze the situation and output a single bash command that, when run, restores the cluster.

Rules:
- "diagnosis": 1-2 sentences identifying the root cause of EACH issue.
- "proposed_fix": a single bash command (use && to chain multiple steps). Must start with "kubectl".
- Do NOT use placeholders — use exact pod/deployment names from the data below.
- Do NOT propose superficial fixes (e.g. just "kubectl delete pod") — fix the underlying configuration so the pod will stay healthy.
- If you are confident in the root cause, output the fix command that resolves it permanently.
- If you need more information, output a diagnostic command (e.g. "kubectl describe pod ..." or "kubectl logs ...") to gather more info. The output will be included in the next cycle's context.

Reply with valid JSON only. Do NOT wrap in markdown or code fences.
Example: {"diagnosis": "Pod nginx-xyz in default is CrashLoopBackOff due to OOM", "proposed_fix": "kubectl delete pod nginx-xyz -n default"}"""

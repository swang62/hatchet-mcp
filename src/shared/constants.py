from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
FILE_DIR = DATA_DIR / "files"
INDEX_PATH = DATA_DIR / "index.json"

COLLECTION_NAME = "knowledge_base"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".log",
    ".env",
    ".tex",
}
HTML_EXTENSIONS = {".html", ".htm"}
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}

# ── LLM / Model ──
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
LLM_TEMPERATURE = 0
INSPECT_TEXT_LIMIT = 8000
CHUNK_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# ── K8s ──
K8S_TIMEOUT = 120
K8S_DEFAULT_LOG_TAIL = 100
K8S_DEFAULT_EVENT_LIMIT = 50
K8S_CONTEXT_EVENT_LIMIT = 20
K8S_EVENT_FILTER_TYPES = {"Warning", "Error"}
K8S_RESTART_THRESHOLD = 3
K8S_MAX_ISSUES = 20
K8S_MAX_PROBLEM_PODS = 3
K8S_VERIFY_POLL_INTERVAL = 5
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
INGEST_EVENT = "ingest:document"
DEFAULT_TASK_NAME = "execute"
WORKFLOW_TIMEOUT = K8S_TIMEOUT

# ── LangGraph ──
GRAPH_RECURSION_LIMIT = 50
DEVOPS_MAX_RETRIES = 3
INSPECT_MAX_RETRIES = 2

# ── MCP ──
MCP_LOG_LEVEL = "WARNING"
MCP_UPLOAD_SOURCE = "mcp_upload"
DEFAULT_SEARCH_K = 5

# ── Misc ──
KUBECTL_CMD = "kubectl"

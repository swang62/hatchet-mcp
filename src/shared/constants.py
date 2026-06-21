from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
FILE_DIR = DATA_DIR / "files"
INDEX_PATH = DATA_DIR / "index.json"

COLLECTION_NAME = "knowledge_base"
VOYAGE_MODEL = "voyage-3-lite"
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

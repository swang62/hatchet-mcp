"""MCP server for the knowledge base.

Two layers of tools:

1. **In-process / one-shot** — `run_ingest`, `search`. Fire one call and
   get a complete result. `run_ingest` runs the full extraction →
   deep-inspect → chunk → embed → store pipeline in-process and returns
   the result. `search` does hybrid (BM25 + vector) retrieval and
   returns chunks enriched with their source document's metadata.

2. **Hatchet-backed / multi-step** — `ingest_document`, `list_documents`,
   `get_document`. `ingest_document` pushes a kb:ingest event that the
   worker picks up; useful when you want the ingestion to survive
   MCP-server restarts or be triggered externally.

Register in ~/.config/opencode/opencode.json:
    {
      "mcpServers": {
        "knowledge-base": {
          "command": "uv",
          "args": ["run", "python", "src/mcp/kb_server.py"]
        }
      }
    }

Run: just mcp
"""

import json
import uuid
from pathlib import Path

from chromadb import PersistentClient
from hatchet_sdk import Hatchet
from langchain_voyageai import VoyageAIEmbeddings

from mcp.server.fastmcp import FastMCP

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
INDEX_PATH = DATA_DIR / "index.json"
COLLECTION_NAME = "knowledge_base"

hatchet = Hatchet()


# ── helpers ──


def _load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text())
    return {}


def _get_collection():
    client = PersistentClient(str(CHROMA_DIR))
    return client.get_or_create_collection(COLLECTION_NAME)


_model: VoyageAIEmbeddings | None = None


def _get_encoder():
    global _model
    if _model is None:
        _model = VoyageAIEmbeddings()
    return _model


# ── MCP server ──

server = FastMCP("knowledge-base", log_level="WARNING")
collection = _get_collection()
encoder = _get_encoder()


@server.tool()
def run_ingest(file_path: str, source: str = "mcp_upload") -> dict:
    """Run the full RAG ingestion pipeline in-process. Extracts text + title,
    deep-inspects with LLM, chunks, embeds, and stores in ChromaDB +
    index.json. Returns the result when done.

    Use this for one-off ingestion where you want a complete result without
    checking the Hatchet dashboard. For long-running or batch ingestion,
    use `ingest_document` instead (Hatchet-backed).
    """
    from src.langgraph.agents.knowledge_ingestion import graph as ingestion_graph

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    if path.suffix.lower() != ".pdf":
        return {"error": "Only PDF files are supported"}

    doc_id = str(uuid.uuid4())
    state = {
        "file_path": str(path),
        "document_id": doc_id,
        "source": source,
        "text": "",
        "num_pages": 0,
        "toc": [],
        "title": "",
        "summary": "",
        "sections": [],
        "keywords": [],
        "topic": "",
        "doc_type": "",
        "entities": [],
        "chunks": [],
        "num_chunks": 0,
    }
    result = ingestion_graph.invoke(state)
    return {
        "status": "ok",
        "document_id": doc_id,
        "file_name": path.name,
        "title": result.get("title", ""),
        "num_pages": result.get("num_pages", 0),
        "num_chunks": result.get("num_chunks", 0),
        "summary": result.get("summary", ""),
        "topic": result.get("topic", ""),
        "doc_type": result.get("doc_type", ""),
        "keywords": result.get("keywords", []),
        "entities": result.get("entities", []),
    }


@server.tool()
def ingest_document(file_path: str, source: str = "mcp_upload") -> dict:
    """Push a kb:ingest event to Hatchet. The worker picks it up and runs
    the full pipeline asynchronously. Use this for batch ingestion or
    when you want durability across MCP-server restarts. For one-off
    ingestion with a complete result, use `run_ingest` instead.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    if path.suffix.lower() != ".pdf":
        return {"error": "Only PDF files are supported"}

    doc_id = str(uuid.uuid4())
    hatchet.event.push(
        "kb:ingest",
        {
            "file_path": str(path),
            "document_id": doc_id,
            "source": source,
        },
    )
    return {
        "status": "accepted",
        "document_id": doc_id,
        "file_name": path.name,
        "message": f"Ingestion started for {path.name}. Check Hatchet dashboard for progress.",
    }


@server.tool()
def search(query: str, k: int = 5) -> dict:
    """Hybrid (BM25 + vector) search over the knowledge base. Returns chunks
    enriched with their source document's metadata (title, file path, summary,
    topic, doc_type, keywords, entities) so the LLM has full context to answer
    the question and cite sources.
    """
    query_embedding = encoder.embed_query(query)
    results = collection.query(
        query_texts=[query],  # BM25
        query_embeddings=[query_embedding],  # vector
        n_results=k,
    )

    index = _load_index()
    chunks: list[dict] = []
    if not results.get("documents") or not results["documents"][0]:
        return {"query": query, "num_results": 0, "chunks": []}

    for i, doc in enumerate(results["documents"][0]):
        chunk_meta = results["metadatas"][0][i] if results["metadatas"] else {}
        doc_id = chunk_meta.get("document_id", "")
        doc_info = index.get(doc_id, {})
        chunks.append(
            {
                "content": doc,
                "score": float(results["distances"][0][i]) if results["distances"] else 0.0,
                "chunk_metadata": chunk_meta,
                "source_document": {
                    "file_name": doc_info.get("file_name", ""),
                    "file_path": doc_info.get("file_path", ""),
                    "title": doc_info.get("title", ""),
                    "summary": doc_info.get("summary", ""),
                    "topic": doc_info.get("topic", ""),
                    "doc_type": doc_info.get("doc_type", ""),
                    "keywords": doc_info.get("keywords", []),
                    "entities": doc_info.get("entities", []),
                    "ingested_at": doc_info.get("ingested_at", ""),
                },
            }
        )
    return {
        "query": query,
        "num_results": len(chunks),
        "chunks": chunks,
    }


@server.tool()
def list_documents() -> dict:
    """List all ingested documents with metadata, summary, and sections."""
    return _load_index()


@server.tool()
def get_document(document_id: str) -> dict:
    """Get full document details and all chunks for a specific document."""
    index = _load_index()
    info = index.get(document_id, {})
    if not info:
        return {"error": f"Document {document_id} not found"}

    results = collection.get(where={"document_id": document_id})
    chunks = []
    for i, doc in enumerate(results["documents"]):
        chunks.append(
            {
                "content": doc,
                "metadata": results["metadatas"][i] if results["metadatas"] else {},
            }
        )
    return {"info": info, "chunks": chunks}


if __name__ == "__main__":
    server.run(transport="stdio")

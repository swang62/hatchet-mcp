"""MCP server: knowledge base tools (ingest, search, list, get)."""

import json
from pathlib import Path

from chromadb import PersistentClient
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.shared.constants import (
    CHROMA_DIR,
    COLLECTION_NAME,
    DEFAULT_SEARCH_K,
    INDEX_PATH,
    MCP_LOG_LEVEL,
    MCP_UPLOAD_SOURCE,
)
from src.shared.hatchet import get_hatchet

load_dotenv()

hatchet = get_hatchet()
server = FastMCP("knowledge-base", log_level=MCP_LOG_LEVEL)


def _load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text())
    return {}


_collection = None


def _get_collection():
    global _collection  # noqa: PLW0603
    if _collection is None:
        _collection = PersistentClient(str(CHROMA_DIR)).get_or_create_collection(COLLECTION_NAME)
    return _collection


@server.tool()
def ingest_document(file_path: str, source: str = MCP_UPLOAD_SOURCE) -> dict:
    """Push an ingest:document event to Hatchet. Worker runs extract, inspect, chunk, embed, store."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    import uuid

    doc_id = str(uuid.uuid4())
    hatchet.event.push(
        "ingest:document",
        {"file_path": str(path), "document_id": doc_id, "source": source},
    )
    return {
        "status": "accepted",
        "document_id": doc_id,
        "file_name": path.name,
        "message": f"Ingestion started for {path.name}. Check Hatchet dashboard for progress.",
    }


@server.tool()
def search(query: str, k: int = DEFAULT_SEARCH_K) -> dict:
    """Vector search using ChromaDB's built-in embedding function. Returns chunks enriched with document metadata."""
    collection = _get_collection()
    results = collection.query(query_texts=[query], n_results=k)

    index = _load_index()
    chunks: list[dict] = []
    documents = results.get("documents")
    if not documents or not documents[0]:
        return {"query": query, "num_results": 0, "chunks": []}

    for i, doc in enumerate(documents[0]):
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
    return {"query": query, "num_results": len(chunks), "chunks": chunks}


@server.tool()
def list_documents() -> dict:
    """List all ingested documents with metadata."""
    return _load_index()


@server.tool()
def search_documents(query: str) -> dict:
    """Search the document index by filename, title, summary, topic, keywords, entities, or doc_type. Returns matching documents with their metadata."""
    index = _load_index()
    query_lower = query.lower()
    results: list[dict] = []
    for doc_id, info in index.items():
        fields = (
            [
                str(info.get("file_name", "")),
                str(info.get("title", "")),
                str(info.get("summary", "")),
                str(info.get("topic", "")),
                str(info.get("doc_type", "")),
            ]
            + [str(k) for k in info.get("keywords", [])]
            + [str(e) for e in info.get("entities", [])]
        )
        if any(query_lower in f.lower() for f in fields):
            results.append({"document_id": doc_id, **info})
    return {"query": query, "num_results": len(results), "documents": results}


@server.tool()
def delete_document(document_id: str) -> dict:
    """Delete a document and all its chunks from ChromaDB, the index, and file storage."""
    index = _load_index()
    info = index.get(document_id)
    if not info:
        return {"error": f"Document {document_id} not found in index"}

    collection = _get_collection()
    collection.delete(where={"document_id": document_id})

    file_path = Path(info["file_path"])
    if file_path.exists():
        file_path.unlink()

    del index[document_id]
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    return {
        "status": "deleted",
        "document_id": document_id,
        "file_name": info["file_name"],
        "title": info.get("title", ""),
        "summary": info.get("summary", ""),
    }


@server.tool()
def get_document(document_id: str) -> dict:
    """Get full document details and all chunks for a document."""
    index = _load_index()
    info = index.get(document_id, {})
    if not info:
        return {"error": f"Document {document_id} not found"}

    collection = _get_collection()
    results = collection.get(where={"document_id": document_id})
    docs = results["documents"] or []
    metadatas = results["metadatas"] or []
    chunks = []
    for i, doc in enumerate(docs):
        chunks.append({"content": doc, "metadata": metadatas[i] if metadatas else {}})
    return {"info": info, "chunks": chunks}


if __name__ == "__main__":
    server.run(transport="stdio")

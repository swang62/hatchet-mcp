"""Hatchet workflow: knowledge ingestion.

Triggered by the kb:ingest event. Runs the LangGraph ingestion graph
which extracts, inspects, chunks, embeds, tags, and stores a PDF.
"""

import uuid
from pathlib import Path

from hatchet_sdk import Context

from src.langgraph.agents.knowledge_ingestion import graph as ingestion_graph


def run_ingestion(input: dict, ctx: Context) -> dict:
    file_path = input.get("file_path", "")
    if not file_path or not Path(file_path).exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    doc_id = input.get("document_id", str(uuid.uuid4()))

    state = {
        "file_path": str(Path(file_path).resolve()),
        "document_id": doc_id,
        "source": input.get("source", "unknown"),
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
    ctx.log(f"Ingested {result['num_chunks']} chunks from {result['num_pages']} pages as {doc_id}")

    return {
        "document_id": doc_id,
        "num_chunks": result["num_chunks"],
        "num_pages": result["num_pages"],
        "title": result.get("title", ""),
        "topic": result.get("topic", ""),
        "doc_type": result.get("doc_type", ""),
        "summary": result.get("summary", ""),
        "keywords": result.get("keywords", []),
    }

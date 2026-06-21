"""Hatchet workflow: knowledge ingestion.

Invokes the LangGraph graph and relies on LangSmith tracing for per-node visibility.
"""

import uuid
from pathlib import Path

from hatchet_sdk import Context

from src.hatchet_worker.models import KnowledgeIngestionInput
from src.langgraph.agents.knowledge_ingestion import IngestionState
from src.langgraph.agents.knowledge_ingestion import graph as kb_graph


def prepare_state(input: KnowledgeIngestionInput) -> IngestionState:
    path = Path(input.file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    return {
        "file_path": str(path),
        "document_id": input.document_id if input.document_id else str(uuid.uuid4()),
        "source": input.source,
        "file_type": path.suffix.lower().lstrip(".") or "unknown",
        "text": "",
        "title": "",
        "summary": "",
        "sections": [],
        "keywords": [],
        "topic": "",
        "doc_type": "",
        "entities": [],
        "chunks": [],
        "num_chunks": 0,
        "error": "",
        "inspect_retries": 0,
        "max_retries": 2,
    }


def run_kb_ingestion(input: KnowledgeIngestionInput, ctx: Context) -> dict:
    state = prepare_state(input)
    result = kb_graph.invoke(state)
    ctx.log(
        f"Ingested {result.get('document_id', 'unknown')} ({result.get('num_chunks', 0)} chunks)"
    )
    return {
        "document_id": result.get("document_id", ""),
        "num_chunks": result.get("num_chunks", 0),
        "title": result.get("title", ""),
        "topic": result.get("topic", ""),
        "doc_type": result.get("doc_type", ""),
        "summary": result.get("summary", ""),
        "keywords": result.get("keywords", []),
    }

"""Hatchet workflow: knowledge ingestion (4 tasks for per-step visibility)."""

import uuid
from pathlib import Path
from typing import Any

from hatchet_sdk import Context

from src.hatchet_worker.models import KnowledgeIngestionInput
from src.langgraph.agents.knowledge_ingestion import (
    chunk_text as _chunk_text,
)
from src.langgraph.agents.knowledge_ingestion import (
    deep_inspect as _deep_inspect,
)
from src.langgraph.agents.knowledge_ingestion import (
    extract_text as _extract_text,
)
from src.langgraph.agents.knowledge_ingestion import (
    store_in_chroma as _store_in_chroma,
)


def _infer_file_type(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "unknown"


def _empty_state(**overrides: Any) -> dict:
    state = {
        "file_path": "",
        "document_id": "",
        "source": "",
        "file_type": "",
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
    }
    state.update(overrides)
    return state


def register_tasks(wf: Any) -> None:

    @wf.task(name="extract_text")
    def extract_text_task(input: KnowledgeIngestionInput, ctx: Context) -> dict:
        path = Path(input.file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        doc_id = input.document_id if input.document_id else str(uuid.uuid4())

        partial = _extract_text(
            _empty_state(  # type: ignore[arg-type]
                file_path=str(path),
                document_id=doc_id,
                source=input.source,
                file_type=_infer_file_type(path),
            )
        )
        ctx.log(f"Extracted {len(partial.get('text', ''))} chars from {path.name}")
        return {
            "document_id": doc_id,
            "source": input.source,
            "file_type": _infer_file_type(path),
            "file_path": str(path),
            "text": partial["text"],
            "title": partial["title"],
        }

    @wf.task(name="deep_inspect", parents=[extract_text_task])
    def deep_inspect_task(input: KnowledgeIngestionInput, ctx: Context) -> dict:
        e = ctx.task_output(extract_text_task)
        result = _deep_inspect(_empty_state(**e))  # type: ignore[arg-type]
        ctx.log(f"Deep inspect: topic={result.get('topic', '')}")
        return result

    @wf.task(name="chunk_text", parents=[extract_text_task])
    def chunk_text_task(input: KnowledgeIngestionInput, ctx: Context) -> dict:
        e = ctx.task_output(extract_text_task)
        result = _chunk_text(_empty_state(**e))  # type: ignore[arg-type]
        ctx.log(f"Created {result['num_chunks']} chunks")
        return result

    @wf.task(
        name="store_in_chroma", parents=[extract_text_task, deep_inspect_task, chunk_text_task]
    )
    def store_in_chroma_task(input: KnowledgeIngestionInput, ctx: Context) -> dict:
        e = ctx.task_output(extract_text_task)
        i = ctx.task_output(deep_inspect_task)
        c = ctx.task_output(chunk_text_task)
        _store_in_chroma(
            _empty_state(  # type: ignore[arg-type]
                **e,
                **i,
                chunks=c.get("chunks", []),
                num_chunks=c.get("num_chunks", 0),
            )
        )
        ctx.log(f"Stored {c.get('num_chunks', 0)} chunks for {e['document_id']}")
        return {
            "document_id": e["document_id"],
            "num_chunks": c.get("num_chunks", 0),
            "title": e.get("title", ""),
            "topic": i.get("topic", ""),
            "doc_type": i.get("doc_type", ""),
            "summary": i.get("summary", ""),
            "keywords": i.get("keywords", []),
        }

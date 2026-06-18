"""Knowledge ingestion LangGraph graph.

Processes a PDF through: extract → deep inspect (sections, summary, entities) →
chunk → embed → tag → store in ChromaDB + index.
Maintains a browsable table of contents in data/index.json.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import fitz
from chromadb import PersistentClient
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_voyageai import VoyageAIEmbeddings

from langgraph.graph import END, START, StateGraph

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
PDF_DIR = DATA_DIR / "pdfs"
INDEX_PATH = DATA_DIR / "index.json"
COLLECTION_NAME = "knowledge_base"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


class IngestionState(TypedDict):
    file_path: str
    document_id: str
    source: str
    text: str
    num_pages: int
    toc: list[dict]
    title: str
    summary: str
    sections: list[dict]
    keywords: list[str]
    topic: str
    doc_type: str
    entities: list[str]
    chunks: list[str]
    num_chunks: int


def extract_pdf(state: IngestionState) -> dict:
    doc = fitz.open(state["file_path"])
    num_pages = doc.page_count
    text = "".join(page.get_text() for page in doc)

    raw_toc = doc.get_toc()
    toc = [{"title": entry[1], "page": entry[2], "level": entry[0]} for entry in raw_toc]

    # Title: PDF metadata > first TOC entry > filename stem
    title = (doc.metadata.get("title") or "").strip()
    if not title and toc:
        title = toc[0]["title"]
    if not title:
        title = Path(state["file_path"]).stem

    doc.close()

    return {"text": text, "num_pages": num_pages, "toc": toc, "title": title}


def deep_inspect(state: IngestionState) -> dict:
    sample = state["text"][:8000]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    toc_hint = ""
    if state["toc"]:
        headings = [s["title"] for s in state["toc"]]
        toc_hint = f"\nExtracted table of contents: {', '.join(headings[:20])}"

    prompt = (
        "You are a research document analyst. Analyze this data science document and extract:\n"
        "1. A 2-3 sentence summary\n"
        "2. The main topic (short label, 2-5 words)\n"
        "3. Document type (paper/tutorial/report/manual/blog)\n"
        "4. 5-10 key technical keywords\n"
        "5. Key entities mentioned (methods, algorithms, datasets, models, people)\n"
        "6. Section headings found in the text (in order, with approximate page)\n\n"
        f"Document excerpt:\n{sample}\n{toc_hint}\n\n"
        "Reply as JSON:\n"
        '{\n  "summary": "...",\n  "topic": "...",\n  "doc_type": "...",\n'
        '  "keywords": ["...", "..."],\n  "entities": ["...", "..."],\n'
        '  "sections": [{"heading": "...", "level": 1}]\n}'
    )
    rsp = llm.invoke(prompt)
    try:
        data = json.loads(rsp.content)
    except json.JSONDecodeError:
        data = {
            "summary": "",
            "topic": "",
            "doc_type": "unknown",
            "keywords": [],
            "entities": [],
            "sections": [],
        }

    return {
        "summary": data.get("summary", ""),
        "topic": data.get("topic", ""),
        "doc_type": data.get("doc_type", "unknown"),
        "keywords": data.get("keywords", []),
        "entities": data.get("entities", []),
        "sections": data.get("sections", state["toc"]),
    }


def chunk_text(state: IngestionState) -> dict:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_text(state["text"])
    return {"chunks": chunks, "num_chunks": len(chunks)}


def store_in_chroma(state: IngestionState) -> dict:
    client = PersistentClient(str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    pdf_name = Path(state["file_path"]).name
    dest = PDF_DIR / pdf_name
    shutil.copy2(state["file_path"], str(dest))

    model = VoyageAIEmbeddings()
    embeddings = model.embed_documents(state["chunks"])

    ids = [f"{state['document_id']}_{i}" for i in range(state["num_chunks"])]
    # ChromaDB metadata values must be scalars (str/int/float/bool), so lists
    # are joined into comma-separated strings. Search splits them back out.
    metadatas = [
        {
            "document_id": state["document_id"],
            "source": state["source"],
            "chunk_index": str(i),
            "topic": state["topic"],
            "doc_type": state["doc_type"],
            "file_name": pdf_name,
            "file_path": str(dest),
            "title": state.get("title", ""),
            "keywords": ", ".join(state.get("keywords", [])),
            "entities": ", ".join(state.get("entities", [])),
        }
        for i in range(state["num_chunks"])
    ]

    collection.add(
        ids=ids,
        documents=state["chunks"],
        embeddings=embeddings,
        metadatas=metadatas,
    )

    entry = {
        "document_id": state["document_id"],
        "file_name": pdf_name,
        "file_path": str(dest),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "file_size": dest.stat().st_size,
        "num_pages": state["num_pages"],
        "num_chunks": state["num_chunks"],
        "title": state.get("title", ""),
        "summary": state["summary"],
        "topic": state["topic"],
        "keywords": state["keywords"],
        "doc_type": state["doc_type"],
        "entities": state["entities"],
        "sections": state["sections"],
    }

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    if INDEX_PATH.exists():
        index = json.loads(INDEX_PATH.read_text())
    else:
        index = {}
    index[state["document_id"]] = entry
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    msg = f"Stored {state['num_chunks']} chunks for {state['document_id']}"
    return {"result": msg}


graph = (
    StateGraph(IngestionState)
    .add_node("extract_pdf", extract_pdf)
    .add_node("deep_inspect", deep_inspect)
    .add_node("chunk_text", chunk_text)
    .add_node("store_in_chroma", store_in_chroma)
    .add_edge(START, "extract_pdf")
    .add_edge("extract_pdf", "deep_inspect")
    .add_edge("deep_inspect", "chunk_text")
    .add_edge("chunk_text", "store_in_chroma")
    .add_edge("store_in_chroma", END)
    .compile()
)

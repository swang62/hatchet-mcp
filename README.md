# Agentic AI Workflows — LangGraph + Hatchet

Durable AI agents with human-in-the-loop, powered by LangGraph for agent logic and Hatchet for reliable orchestration.

---

## Quick start

```bash
# Install deps
uv sync

# Start Hatchet infrastructure
just infra

# Open Hatchet Dashboard at http://localhost:8888
# Login: admin@example.com / Admin123!!
# Create a tenant, generate API token, paste into .env

# Start the worker
just worker

# In another terminal — dev the LangGraph graphs in LangSmith Studio
just dev
```

---

## What's here

| Agent | Trigger | What it does |
|---|---|---|
| **Knowledge Ingestion** | `kb:ingest` event | Ingests PDFs, extracts text, deep-inspects (sections/summary/entities), semantically chunks, embeds with Voyage AI, tags with LLM, stores in ChromaDB. Exposes RAG via MCP server. |
| **K8s DevOps** | `kb:k8s:monitor` event or cron | Watches local K8s cluster, detects errors, diagnoses with LLM, attempts auto-fixes via kubectl, escalates to HITL when stuck. |

---

## Architecture

```
External system / CLI trigger
  │
  ├── Hatchet event push ──────────▶ Hatchet (durable orchestration)
  │                                    │
  │                                    ├── Workflow: knowledge_ingestion
  │                                    │   └── Runs LangGraph graph
  │                                    │       extract → inspect → chunk → embed → tag → store
  │                                    │
  │                                    └── Hatchet Dashboard ─── monitor, retry
  │
  ├── MCP Server (kb_server.py) ────▶ Any LLM client (opencode, Claude, etc.)
  │   exposes:
  │     in-process:    run_ingest(), search()      ← one-call, returns result
  │     hatchet-backed: ingest_document(), list_documents(), get_document()
  │
  └── MCP Server (k8s_server.py) ───▶ Any LLM client
      exposes:
        simple tools:  check_pods(), get_logs(), describe_pod(),
                        get_events(), debug_pod(), run_kubectl()
        one-shot agent: run_devops_agent(task)      ← autonomous, returns result
      (talks to your kubeconfig cluster — k3d, kind, minikube, real)
```

---

## Agents

### Knowledge Base Ingestion

Processes data science PDFs into a searchable RAG knowledge base:

1. **Extract** — text + TOC from PDF via pymupdf
2. **Deep inspect** — LLM extracts summary, sections, keywords, entities, doc type
3. **Chunk** — semantic chunking via LangChain text splitters
4. **Embed** — Voyage AI embeddings
5. **Store** — ChromaDB at `data/chroma_db/`, PDFs copied to `data/pdfs/`, index at `data/index.json`

```bash
# Trigger ingestion of a PDF
just ingest path/to/document.pdf
```

Search the knowledge base from any MCP-compatible LLM:

```json
// ~/.config/opencode/opencode.json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "uv",
      "args": ["run", "python", "src/mcp/kb_server.py"]
    }
  }
}
```

### K8s DevOps Agent (on-demand via MCP)

Personal K8s debugging and operations, exposed as MCP tools. Talks to
whichever cluster is in your kubeconfig (k3d, kind, minikube, real).

Two layers of tools:

**Simple data tools** — use when you want to inspect or operate yourself:

- `check_pods` — list CrashLoop / ImagePull / Error / high-restart pods
- `get_logs` — recent logs from a pod (with container filter)
- `describe_pod` — pod spec, status, container states, conditions
- `get_events` — recent Warning / Error events
- `debug_pod` — one-shot: describe + logs + events for a pod
- `run_kubectl` — run any kubectl command, return stdout/stderr/returncode

**`run_devops_agent(task)`** — fire-and-wait autonomous agent. Runs the
langgraph graph end-to-end (check cluster → diagnose with logs + events +
history → kubectl fix → verify → self-correct up to 3 times) in-process
and returns a complete result. Use this when you want a finished answer
without chaining tools yourself.

```json
// ~/.config/opencode/opencode.json
{
  "mcpServers": {
    "k8s-devops": {
      "command": "uv",
      "args": ["run", "python", "src/mcp/k8s_server.py"]
    }
  }
}
```

Then in opencode:
- *"Why is nginx crashing?"* → simple tools (`check_pods` → `get_logs` → `describe_pod`)
- *"Fix the broken pods in default"* → `run_devops_agent` does it all and reports back

---

## Commands

| Command | Description |
|---|---|
| `just infra` | Start Hatchet Lite + Postgres via Docker |
| `just infra-stop` | Stop Hatchet infrastructure |
| `just dev` | Launch LangSmith Studio (hot-reload for graphs) |
| `just worker` | Start Hatchet worker (registers all agents) |
| `just ingest <path>` | Trigger KB ingestion for a PDF (Hatchet path) |
| `just mcp` | Run the MCP knowledge base server (stdio) |
| `just k8s-mcp` | Run the MCP K8s devops server (stdio) |
| `just inspect` | Open MCP inspector against the KB server |
| `just inspect-k8s` | Open MCP inspector against the K8s server |
| `just sync` | uv sync (install/update deps) |

---

## Project structure

```
├── pyproject.toml              # Python deps
├── langgraph.json              # LangGraph CLI config
├── Justfile                    # Task runner
├── docker-compose.hatchet.yml  # Hatchet Lite self-host
├── .env.example
│
├── src/
│   ├── langgraph/
│   │   └── agents/
│   │       ├── knowledge_ingestion.py   # LangGraph graph
│   │       └── k8s_devops.py            # LangGraph graph
│   │
│   ├── hatchet_worker/
│   │   ├── worker.py                    # Registers all workflows
│   │   └── workflows/
│   │       ├── knowledge_ingestion.py   # Hatchet task wrapper
│   │       └── k8s_devops.py            # Hatchet task wrapper
│   │
│   ├── mcp/
│   │   ├── kb_server.py                 # MCP server for RAG
│   │   └── k8s_server.py                # MCP server for K8s debug/ops
│   │
│   ├── k8s.py                           # Shared K8s utilities
│   │
│   ├── trigger_kb_ingest.py
│   └── trigger_k8s_check.py
│
└── data/
    ├── pdfs/                    # Ingested PDFs
    ├── chroma_db/               # ChromaDB vector store
    └── index.json               # Document table of contents
```

## Adding more agents and MCP tools

**New MCP tool** (e.g. for a different cluster, API, or local service):

1. Create `src/mcp/<name>_server.py` with `FastMCP("<name>")` and `@server.tool()` functions
2. Add a `just <name>-mcp` recipe in the `Justfile`
3. Register the server in your LLM client's MCP config

**New LangGraph agent** (e.g. for a new durable workflow):

1. Create `src/langgraph/agents/<name>.py` with `StateGraph(...)` and a `graph` variable
2. Add it to `langgraph.json` so it shows up in LangSmith Studio
3. (Optional) Create `src/hatchet_worker/workflows/<name>.py` and register it in `src/hatchet_worker/worker.py` if you want it triggered via Hatchet events
4. (Optional) Create `src/trigger_<name>.py` for ad-hoc CLI triggers

**Shared helpers**: if two agents or servers need the same logic (e.g. K8s client, DB connection), put it in `src/<topic>.py` and import.

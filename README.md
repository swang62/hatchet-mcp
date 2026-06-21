# Agentic AI Workflows — LangGraph + Hatchet

Durable AI agents with human-in-the-loop, powered by LangGraph for agent logic and Hatchet for reliable orchestration.

---

## Quick start

```bash
uv sync                            # install deps
just infra                         # start Hatchet infra (postgres, rabbitmq, etc.)
# Open http://localhost:8888, login: admin@example.com / Admin123!!
# Create a tenant, generate API token, paste into .env
just worker                        # start worker (runs LangGraph graphs as Hatchet tasks)
just mcp                           # start MCP server (stdio)
just dev                           # dev graphs in LangSmith Studio
```

---

## What's here

| Agent | How to trigger |
|---|---|
| **Knowledge Ingestion** | `ingest:document` event — ingests PDFs, extracts text, embeds with Voyage AI, stores in ChromaDB. RAG via MCP. |
| **K8s DevOps Agent** | `k8s:devops` event — full LangGraph loop: check cluster, diagnose with LLM, auto-fix via kubectl, verify, self-correct up to 3x. |
| **K8s Tools** | `admin.run_workflow("k8s_tool", ...)` — individual ops (check_pods, get_logs, describe_pod, run_kubectl, etc.) routed through Hatchet for dashboard visibility. |

---

## Architecture

```
LLM client (opencode, claude, etc.)
  │
  ├── MCP Server (kb_server.py)    ◄── stdio
  │     ├── ingest_document()      ──▶ event push ──▶ Worker
  │     ├── search()
  │     └── get_document()         ──▶ in-process (read-only)
  │
  └── MCP Server (k8s_server.py)   ◄── stdio
        ├── check_pods, get_logs,  ──▶ sync via admin.run_workflow
        │   describe_pod, etc.
        └── run_devops_agent()     ──▶ event push ──▶ Worker ──▶ LangGraph

                     ┌──────────────────────────────┐
                     │  Hatchet Worker               │
                     │  ├─ knowledge_ingestion       │
                     │  ├─ k8s_devops                │
                     │  └─ k8s_tool                  │
                     │  All runs visible in dashboard │
                     └──────────────────────────────┘
```

---

## Agents

### Knowledge Base Ingestion

Processes PDFs into a searchable RAG knowledge base: extract text, deep-inspect (summary, sections, entities), semantically chunk, embed with Voyage AI, store in ChromaDB.

```bash
just dev-ingest path/to/document.pdf   # run directly, no Hatchet
```

### K8s DevOps Agent

Personal K8s debugging via MCP. All kubectl commands run on the Hatchet worker (visible in dashboard). Talks to whatever cluster is in your kubeconfig.

```bash
just dev-k8s "fix the broken pods in default"   # run the full LangGraph loop
```

Then in opencode:
- *"Why is nginx crashing?"* — runs individual tools (check_pods → get_logs → describe_pod)
- *"Fix the broken pods in default"* — `run_devops_agent` does the full loop

### MCP config

Register the servers in your LLM client:

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "uv",
      "args": ["run", "python", "src/mcp/kb_server.py"]
    },
    "k8s-devops": {
      "command": "uv",
      "args": ["run", "python", "src/mcp/k8s_server.py"]
    }
  }
}
```

---

## Dev testing

LangGraph graphs are pure business logic (zero Hatchet imports). Test them directly:

```python
from src.langgraph.agents.knowledge_ingestion import graph

result = graph.invoke({
    "file_path": "/path/to/doc.pdf",
    "document_id": "test-123",
    "source": "dev",
})
```

---

## Adding agents and MCP tools

1. Create `src/langgraph/agents/<name>.py` with `StateGraph(...)` and a `graph` variable
2. Create `src/hatchet_worker/workflows/<name>.py` — wraps the graph in a Hatchet task
3. Register it in `src/hatchet_worker/worker.py` with an `on_events=[...]` trigger
4. (Optional) Create `src/mcp/<name>_server.py` with `FastMCP` and `@server.tool()` functions
5. Add a `just <name>-mcp` recipe in the `Justfile`

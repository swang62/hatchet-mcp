# Personal Agentic AI - Hatchet MCP

This is my personal local AI agent setup that can run durable and fully traceable agents (with LangGraph), utilizing a universal MCP interface. The MCP directly talks to a Hatchet server, which then triggers my custom tasks/workflows, making it trivial to hook up any local LLM chat interface (LMStudio, OpenCode, Claude Code, Open WebUI, etc) and run custom AI workflows. This has the added benefit of full logging, custom loops, orchestration, retries, tracing, and all other goodies provided by Hatchet.

---

## Quick start

```bash
uv sync                            # install deps (this is only required for local dev)
just docker-start                  # start Hatchet orchestration server in Docker (localhost:8888)
just worker                        # start local worker (runs LangGraph locally, no Docker)
just dev                           # run LangGraph Studio to visualize and debug graphs
```

## Currently available agents

| Agent | How to trigger |
|---|---|
| **Knowledge Management** | ingests files, extracts text, vector embeddings, deep inspection with LLM, RAG retrieval, file indexing |
| **K8s DevOps Troubleshooter** | full LangGraph agent loop: check cluster, diagnose with LLM, auto-fix via kubectl, verify, self-correct |
| **K8s Direct Tools** | individual k8s ops (check_pods, get_logs, describe_pod, run_kubectl, etc.) routed through Hatchet |

## Architecture

```
LLM client (opencode, claude, etc.)
  │
  ├── MCP Server (kb_server.py)    ◄── stdio
  │     ├── ingest_document        ──▶ event push to Worker
  │     ├── search, get_document
  │     ├── list_documents, search_documents
  │     └── delete_document
  │
  └── MCP Server (k8s_server.py)   ◄── stdio
        ├── check_pods, get_logs, describe_pod
        ├── get_events, debug_pod, run_kubectl
        ├── get_deployments, get_statefulsets, get_daemonsets
        ├── get_services, get_ingresses, get_configmaps
        ├── get_secrets, exec_in_pod
        └── run_devops_agent       ──▶ event push to Worker

                     ┌──────────────────────────────┐
                     │  Hatchet Worker               │
                     │  ├─ knowledge_ingestion       │
                     │  ├─ k8s_devops                │
                     │  └─ k8s_tool                  │
                     │  All runs visible in dashboard │
                     └──────────────────────────────┘
```

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

### Worker management

Register the worker as a macOS launchd service (auto-starts on login):

```bash
serviceman add --name hatchet-worker -- /Users/steve/dev/hatchet-mcp/hatchet-worker.sh
```

Restart the worker after code changes:

```bash
serviceman restart hatchet-worker
```

# Local K8s DevOps Agent (hitl branch)

This is my local AI agent setup that can run durable and fully traceable devOps agents to troubleshoot and manage my K8S clusters, using the universal MCP interface. Compared to asking an LLM to execute pure bash commands, this approach has the added benefit of full audit trails and explicit approvals, by using an orchestration layer.

### Features

- **Full K8s agent self-correcting loop** — check cluster, diagnose, execute fixes, verify, retry until exhausted
- **Human-in-the-loop approval** — agent pauses before every fix and waits for you to approve or reject
- **Direct K8s tools** — individual MCP tools for checking pods, logs, deployments, events, kubectl, and more through chat interface
- **Scheduled nightly runs** — daily checks at 2 AM with optional push notifications when issues are found
- **Durable execution** — runs survive crashes, retry from last checkpoint, stop and resume at any point
- **Traceability** — full logging from every agent run, every LLM call and bash command is recorded

---

## Quick start

```bash
uv sync                            # install deps (this is only required for local dev)
just docker-start                  # start Hatchet orchestration server in Docker (localhost:8888)
just worker                        # start local worker (runs LangGraph locally, no Docker)
just dev                           # run LangGraph Studio to visualize and debug graphs
```

## Architecture

```
LLM client (opencode, claude, codex, etc.)
  │
  └── MCP Server (k8s_server.py)   ◄── communicates with Hatchet server
        ├── check_pods, get_logs, describe_pod
        ├── get_events, debug_pod, run_kubectl
        ├── get_deployments, get_statefulsets, get_daemonsets
        ├── get_services, get_ingresses, get_configmaps
        ├── get_secrets, exec_in_pod
        └── run_devops_agent       ──▶ event push to local Hatchet worker

                     ┌──────────────────────────────┐
                     │  Hatchet Worker              │
                     │  ├─ k8s_devops               │
                     │  ├─ k8s_devops_resume        │
                     │  └─ k8s_tool                 │
                     └──────────────────────────────┘
```

### MCP config

Register the servers in your LLM client:

```json
{
  "mcpServers": {
    "k8s-devops": {
      "command": "uv",
      "args": ["run", "python", "src/mcp/k8s_server.py"]
    }
  }
}
```

## Adding agents and MCP tools

1. Create `src/langgraph/agents/<name>.py` with `StateGraph(...)` and a `graph` variable
2. Create `src/hatchet_worker/workflows/<name>.py` — wraps the graph in a Hatchet task
3. Register it in `src/hatchet_worker/worker.py` with an `on_events=[...]` trigger
4. (Optional) Create `src/mcp/<name>_server.py` with `FastMCP` and `@server.tool()` functions

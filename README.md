# Local K8s DevOps Agent (hitl parent)

This is my local AI agent setup that can run durable and fully traceable devOps agents to troubleshoot and manage my K8S clusters, using the universal MCP interface. Compared to asking an LLM to execute pure bash commands, this approach has the added benefit of full audit trails and explicit approvals, by using an orchestration layer.

### Features

- **Full K8s agent self-correcting loop** — check cluster, diagnose, execute fixes, verify, retry until exhausted
- **Human-in-the-loop approval** — agent pauses before every fix (ignores safe read-only changes) and waits for approval
- **Direct K8s tools** — individual MCP tools for checking pods, logs, deployments, events, kubectl, and more through chat interface
- **Scheduled nightly runs** — daily checks at 2 AM with optional push notifications when issues are found
- **Durable execution** — runs survive crashes, retry from last checkpoint, stop and resume at any point
- **Traceability** — full logging from every agent run, every LLM call and bash command is recorded in Hatchet

---

## Quick start

```bash
uv sync            # install deps (this is only required for local dev)
just start         # start Hatchet orchestration server in Docker (localhost:8888)
just worker        # start local worker (runs LangGraph locally, see below for launchd)
just dev           # run LangGraph Studio to visualize and debug graphs
```

## Architecture

```
LLM client (opencode, claude, codex, etc.)
  │
  └── MCP Server (k8s_server.py)   ◄── communicates with Hatchet server
        ├── k8s_inspect             — unified cluster inspection
        ├── k8s_run_agent           — run the autonomous devops agent with an initial prompt/goal
        ├── k8s_resume              — HITL approval lifecycle
        └── k8s_exec_kubectl        — raw kubectl escape hatch

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

### Worker management

Register the worker as a macOS launchd service (auto-starts on login):

```bash
serviceman add --name hatchet-worker -- /Users/steve/dev/hatchet-mcp/hatchet-worker.sh
```

Restart the worker after code changes:

```bash
serviceman restart hatchet-worker
```

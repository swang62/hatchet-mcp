# Local K8s DevOps Agent

This is my local AI agent setup that can run durable and fully traceable devOps agent workflows to help troubleshoot and manage my K8S clusters, using a MCP server as the control plane. Compared to using an LLM or agent harness to execute pure bash commands in the terminal, this approach has the added benefit of full audit trails and explicit approvals, by using an orchestration layer provided by Hatchet. It also has a much faster learning curve compared to traditional dashboards like LangFlow/Flowise/Dify, as the MCP interface hides all the complexity behind natural language interactions.

### Features

- **Full K8s agent self-correcting loop** — check cluster, diagnose, execute fixes, verify, retry until exhausted
- **Human-in-the-loop approval** — agent pauses before every fix (ignores safe read-only changes) and waits for approval
- **Direct K8s tools** — individual MCP tools for checking pods, logs, deployments, events, kubectl, and more through chat interface
- **Scheduled nightly runs** — daily checks at 2 AM with optional push notifications when issues are found
- **Durable execution** — runs survive crashes, retry from last checkpoint, stop and resume at any point
- **Traceability** — full logging from every agent run, every LLM call and bash command is recorded in Hatchet

---

## Quick start
Once you have hatchet server/worker up and running, you can access the hatchet dashboard at http://localhost:8888 to view all logs. Full traces are available for every tool that the MCP server has access to.

```bash
just start         # start the Hatchet orchestration server in Docker (localhost:8888)
just worker        # start a single local worker (runs locally to access your kubeconfig/kubectl)
just dev           # run LangGraph Studio to visualize nodes and useful debugging tools
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

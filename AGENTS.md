# K8s DevOps Agent — Project Notes

## Worker management

The worker runs as a macOS launchd service managed by `serviceman`:

```bash
serviceman restart hatchet-worker   # restart after code changes
serviceman add --name hatchet-worker -- /path/to/hatchet-worker.sh   # register on login
```

The worker runs `src/hatchet_worker/worker.py` which registers three Hatchet workflows (`k8s_check`, `k8s_resume`, `k8s_tools`). Any changes to workflow code require a restart to take effect.

## Project structure

```
src/
  mcp/k8s_server.py           — MCP tools (entry point for LLM clients)
  hatchet_worker/
    worker.py                 — Worker registration + cron
    workflows/                — Hatchet workflow implementations
  langgraph/agents/           — LangGraph agent graph
  shared/                     — Bridge layer between hatchet and langgraph
```

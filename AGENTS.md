## Project layout

```
src/
  mcp/              -- MCP server (entry point for LLM clients)
  hatchet_worker/   -- Hatchet worker + workflow implementations
  langgraph/        -- LangGraph agent graph
  shared/           -- Bridge layer between hatchet and langgraph
```

## Gotchas

**NEVER auto-approve HITL requests:**
Do not call `k8s_resume approve` on any thread unless the user explicitly tells you to. The agent always pauses at `approve_fix` for human approval. Only the user decides when to approve or reject.

**MCP universal 60s timeout:**
Every MCP tool call times out after 60 seconds. The HITL interrupt resets the timer. If a tool call returns with `needs_approval`, the user must approve/reject via `k8s_resume` before the thread can continue. Do not poll or automate approvals on behalf of the user.

**Hatchet cron is UTC-only:**
No timezone parameter exists. The expression is hardcoded in `scheduling.py:53`. Changing the local time requires computing the equivalent UTC hour manually, and there is no DST handling.

**Worker restart via serviceman (macOS launchd):**
`serviceman restart hatchet-worker` after any code change to workflow or worker files. Killing and re-running the process manually is not sufficient for a clean restart. The script is at repo root (`hatchet-worker.sh`) — it runs `uv run python src/hatchet_worker/worker.py`. To register the worker as a login service:
```bash
serviceman add --name hatchet-worker -- ./hatchet-worker.sh
```

**Two entrypoints, different purposes:**
- MCP server: `uv run python src/mcp/k8s_server.py` — for LLM clients
- Hatchet worker: `uv run python src/hatchet_worker/worker.py` — durable background agent

**`just lint` = 3 tools:**
`ruff check src/ && ruff format src/ --check && basedpyright src/`. Running only `ruff check` skips type-checking and format verification.

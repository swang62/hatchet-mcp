infra:
    docker compose -f docker-compose.hatchet.yml up -d

infra-stop:
    docker compose -f docker-compose.hatchet.yml down

dev:
    uv run langgraph dev

worker:
    uv run python src/hatchet_worker/worker.py

ingest path:
    uv run python src/trigger_kb_ingest.py {{path}}

k8s-check:
    uv run python src/trigger_k8s_check.py

mcp:
    uv run python src/mcp/kb_server.py

inspect:
    npx @modelcontextprotocol/inspector uv run python src/mcp/kb_server.py

inspect-k8s:
    npx @modelcontextprotocol/inspector uv run python src/mcp/k8s_server.py

k8s-mcp:
    uv run python src/mcp/k8s_server.py

sync:
    uv sync

docker-start:
    docker compose -f docker-compose.hatchet.yml up -d --force-recreate

docker-stop:
    docker compose -f docker-compose.hatchet.yml down

inspect-kb:
    npx @modelcontextprotocol/inspector uv run python src/mcp/kb_server.py

inspect-k8s:
    npx @modelcontextprotocol/inspector uv run python src/mcp/k8s_server.py

dev:
    langgraph dev

worker:
    uv run python src/hatchet_worker/worker.py

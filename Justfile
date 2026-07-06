start:
    docker compose -f docker-compose.hatchet.yml up -d --force-recreate

stop:
    docker compose -f docker-compose.hatchet.yml down

inspect:
    npx @modelcontextprotocol/inspector uv run python src/mcp/k8s_server.py

dev:
    uv run langgraph dev

worker:
    uv run python src/hatchet_worker/worker.py

lint:
    uv run ruff check src/ && uv run ruff format src/ --check && uv run basedpyright src/

test:
    uv run pytest tests/

test-cleanup:
    kubectl delete deployment nginx-demo cm nginx-config --ignore-not-found 2>/dev/null || true

test-broken:
    kubectl delete deployment nginx-demo cm nginx-config --ignore-not-found 2>/dev/null || true
    kubectl apply -f tests/broken-nginx.yaml 2>&1

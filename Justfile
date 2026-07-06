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
    uv run pytest tests/ -v --timeout=180

test-cleanup-nginx:
	kubectl delete deployment nginx-demo cm nginx-config --ignore-not-found 2>/dev/null || true

test-broken-nginx:
	kubectl delete deployment nginx-demo cm nginx-config --ignore-not-found 2>/dev/null || true
	kubectl apply -f tests/broken-nginx.yaml 2>&1
	# wait for pod to exist (it will never be Ready — that's the point)
	kubectl wait --for=condition=ready pod -n default -l app=nginx-demo --timeout=15s 2>&1 || true
	kubectl get pods -n default -l app=nginx-demo -o wide
	@echo "=== Container status ==="
	kubectl describe pod -n default -l app=nginx-demo 2>&1 | sed -n '/Containers:/,$ p' | head -20
	@echo "--- cleanup: just test-cleanup-nginx"

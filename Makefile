.PHONY: help backend frontend \
	test test-backend test-frontend test-cov \
	local local-backend local-frontend local-eval local-stop local-status local-clean \
	mac mac-backend mac-frontend mac-eval mac-stop mac-status mac-clean \
	hpc hpc-backend hpc-frontend hpc-eval hpc-stop hpc-status hpc-clean \
	hpc-slurm hpc-slurm-backend hpc-slurm-frontend hpc-slurm-eval hpc-slurm-stop hpc-slurm-status hpc-slurm-clean \
	docker docker-backend docker-frontend docker-eval docker-stop docker-status docker-clean clean stop status ngrok ngrok-stop ngrok-status

help:
	@echo "WATCHOUT ISEQL -- three-condition ablation study"
	@echo ""
	@echo "  make backend             - Install Python deps via Pipenv"
	@echo "  make frontend            - Install JS deps via pnpm"
	@echo ""
	@echo "  make test               - Run backend + frontend test suites"
	@echo "  make test-backend       - Run backend pytest suite (backend/tests)"
	@echo "  make test-frontend      - Run frontend vitest suite (iseql-model)"
	@echo "  make test-cov           - Run tests with coverage (xml/lcov for Codecov)"
	@echo ""
	@echo "  make local              - Run backend (auto-detect conda + pipenv) + frontend locally"
	@echo "  make local-backend      - Run backend only (auto-detect conda + pipenv)"
	@echo "  make local-frontend     - Run frontend only"
	@echo "  make local-eval         - Run eval queue (local profile)"
	@echo "  make local-stop         - Stop local services"
	@echo "  make local-status       - Status local services"
	@echo "  make local-clean        - Clean local artifacts"
	@echo ""
	@echo "  make mac                - Run backend (brew ffmpeg + CPU pipenv) + frontend on macOS"
	@echo "  make mac-backend        - Backend only on macOS (Pipfile.mac, no CUDA)"
	@echo "  make mac-frontend       - Frontend only"
	@echo "  make mac-eval           - Run eval queue (mac profile)"
	@echo "  make mac-stop           - Stop mac services"
	@echo "  make mac-status         - Status mac services"
	@echo "  make mac-clean          - Clean mac artifacts"
	@echo ""
	@echo "  make hpc                - Frontend on login, backend on GPU node via direct SSH (BACKEND_HOST, default compute-0-3)"
	@echo "  make hpc-backend        - Backend only via direct SSH"
	@echo "  make hpc-frontend       - Frontend only"
	@echo "  make hpc-eval           - Run eval queue (HPC profile, via backend API)"
	@echo "  make hpc-stop           - Stop HPC backend + frontend"
	@echo "  make hpc-status         - Status HPC services"
	@echo "  make hpc-clean          - Clean HPC artifacts"
	@echo ""
	@echo "  make hpc-slurm          - Frontend on login, backend via Slurm (cuda)"
	@echo "  make hpc-slurm-backend  - Backend only via Slurm"
	@echo "  make hpc-slurm-frontend - Frontend only"
	@echo "  make hpc-slurm-eval     - Run eval queue (HPC-Slurm profile, via backend API)"
	@echo "  make hpc-slurm-stop     - Stop HPC-Slurm backend + frontend"
	@echo "  make hpc-slurm-status   - Status HPC-Slurm services"
	@echo "  make hpc-slurm-clean    - Clean HPC-Slurm artifacts"
	@echo ""
	@echo "  make docker             - Build and run both services via docker-compose"
	@echo "  make docker-backend     - Run backend only via docker-compose"
	@echo "  make docker-frontend    - Run frontend only via docker-compose"
	@echo "  make docker-eval        - Run eval queue (docker profile)"
	@echo "  make docker-stop        - Stop docker services"
	@echo "  make docker-status      - Status docker services"
	@echo "  make docker-clean       - Stop and remove docker containers/volumes"
	@echo ""
	@echo "  make clean              - Clean all artifacts"
	@echo "  make status             - Status all profiles"
	@echo "  make stop               - Stop all profiles"
	@echo ""
	@echo "  make ngrok              - Start a public tunnel to the frontend (:5173)"
	@echo "  make ngrok-stop         - Stop the ngrok tunnel"
	@echo "  make ngrok-status       - Show the public ngrok URL"
	cd backend && pipenv sync --dev

frontend:
	cd frontend && pnpm install

test: test-backend test-frontend

test-backend:
	cd backend && PYTHONPATH=src pipenv run pytest

test-frontend:
	cd frontend && pnpm test

test-cov: test-backend-cov test-frontend-cov

test-backend-cov:
	cd backend && PYTHONPATH=src pipenv run pytest --cov=iseql --cov=service.relation_vocab --cov-report=term-missing --cov-report=xml

test-frontend-cov:
	cd frontend && pnpm test:coverage

local-backend:
	PROFILE=local bash scripts/start.sh backend

local-frontend:
	PROFILE=local bash scripts/start.sh frontend

local:
	PROFILE=local bash scripts/start.sh

local-eval:
	PROFILE=local bash scripts/eval.sh

local-stop:
	pkill -f "uvicorn.*8000" 2>/dev/null || true
	pkill -f "vite.*5173" 2>/dev/null || true
	pkill -f "ngrok http" 2>/dev/null || true

local-status:
	@echo "== local status =="
	@curl -s http://localhost:8000/api/health 2>&1 | grep -q '"status":"ok"' && echo "backend: UP (8000)" || echo "backend: DOWN"
	@ss -tlnp 2>/dev/null | grep -q ":8000" && echo "port 8000: LISTEN" || echo "port 8000: -"
	@ss -tlnp 2>/dev/null | grep -q ":5173" && echo "frontend: UP (5173)" || echo "frontend: DOWN"
	@curl -s http://localhost:11434/api/version 2>&1 | grep -q version && echo "ollama: UP (localhost)" || echo "ollama: DOWN"

local-clean:
	rm -rf data/analysis.db data/analysis.db-shm data/analysis.db-wal
	rm -rf frontend/node_modules frontend/.svelte-kit

mac-backend:
	PROFILE=mac bash scripts/start.sh backend

mac-frontend:
	PROFILE=mac bash scripts/start.sh frontend

mac:
	PROFILE=mac bash scripts/start.sh

mac-eval:
	PROFILE=mac bash scripts/eval.sh

mac-stop:
	pkill -f "uvicorn.*8000" 2>/dev/null || true
	pkill -f "vite.*5173" 2>/dev/null || true
	pkill -f "ngrok http" 2>/dev/null || true

mac-status:
	@echo "== mac status =="
	@curl -s http://localhost:8000/api/health 2>&1 | grep -q '"status":"ok"' && echo "backend: UP (8000)" || echo "backend: DOWN"
	@lsof -i :8000 2>/dev/null | grep -q LISTEN && echo "port 8000: LISTEN" || echo "port 8000: -"
	@lsof -i :5173 2>/dev/null | grep -q LISTEN && echo "frontend: UP (5173)" || echo "frontend: DOWN"

mac-clean:
	rm -rf data/analysis.db data/analysis.db-shm data/analysis.db-wal
	rm -rf frontend/node_modules frontend/.svelte-kit

hpc-backend:
	BACKEND_HOST=$${BACKEND_HOST:-compute-0-3} PROFILE=hpc bash scripts/start.sh backend

hpc-frontend:
	BACKEND_HOST=$${BACKEND_HOST:-compute-0-3} PROFILE=hpc bash scripts/start.sh frontend

hpc:
	BACKEND_HOST=$${BACKEND_HOST:-compute-0-3} PROFILE=hpc bash scripts/start.sh

hpc-eval:
	BACKEND_HOST=$${BACKEND_HOST:-compute-0-3} PROFILE=hpc bash scripts/eval.sh

hpc-stop:
	pkill -f "uvicorn.*8000" 2>/dev/null || true
	ssh $${BACKEND_HOST:-compute-0-3} "pkill -f 'uvicorn.*8000' 2>/dev/null || true" 2>/dev/null || true
	pkill -f "ssh.*-L 8000" 2>/dev/null || true
	pkill -f "backend-wake-proxy" 2>/dev/null || true
	@if [ -f $(HOME)/.cache/backend-supervise.pid ]; then kill $$(cat $(HOME)/.cache/backend-supervise.pid) 2>/dev/null || true; rm -f $(HOME)/.cache/backend-supervise.pid; fi
	@if [ -f $(HOME)/.cache/backend-slurm.jobid ]; then scancel $$(cat $(HOME)/.cache/backend-slurm.jobid) 2>/dev/null || true; rm -f $(HOME)/.cache/backend-slurm.jobid; echo "backend Slurm job cancelled"; fi
	rm -f $(HOME)/.cache/backend-wake.need
	pkill -f "vite.*5173" 2>/dev/null || true
	pkill -f "ngrok http" 2>/dev/null || true

hpc-status:
	@echo "== hpc status =="
	@curl -s http://localhost:8000/api/health 2>&1 | grep -q '"status":"ok"' && echo "backend: UP (via tunnel)" || echo "backend: DOWN"
	@ssh -o BatchMode=yes -o ConnectTimeout=3 $${BACKEND_HOST:-compute-0-3} "curl -s http://localhost:11434/api/version 2>&1 | grep -q version && echo 'ollama@$${BACKEND_HOST:-compute-0-3}: UP' || echo 'ollama@$${BACKEND_HOST:-compute-0-3}: DOWN'" 2>/dev/null || echo "ollama@$${BACKEND_HOST:-compute-0-3}: UNREACHABLE"
	@ss -tlnp 2>/dev/null | grep -q ":5173" && echo "frontend: UP (5173)" || echo "frontend: DOWN"
	@curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q public_url && echo "ngrok: UP" || echo "ngrok: DOWN"

hpc-clean:
	rm -rf data/analysis.db data/analysis.db-shm data/analysis.db-wal
	rm -rf frontend/node_modules frontend/.svelte-kit

hpc-slurm-backend:
	PROFILE=hpc-slurm bash scripts/start.sh backend

hpc-slurm-frontend:
	PROFILE=hpc-slurm bash scripts/start.sh frontend

hpc-slurm:
	PROFILE=hpc-slurm bash scripts/start.sh

hpc-slurm-eval:
	PROFILE=hpc-slurm bash scripts/eval.sh

hpc-slurm-stop:
	pkill -f "uvicorn.*8000" 2>/dev/null || true
	ssh $${BACKEND_HOST:-compute-0-3} "pkill -f 'uvicorn.*8000' 2>/dev/null || true" 2>/dev/null || true
	pkill -f "backend-wake-proxy" 2>/dev/null || true
	@if [ -f $(HOME)/.cache/backend-supervise.pid ]; then kill $$(cat $(HOME)/.cache/backend-supervise.pid) 2>/dev/null || true; rm -f $(HOME)/.cache/backend-supervise.pid; fi
	@if [ -f $(HOME)/.cache/backend-slurm.jobid ]; then scancel $$(cat $(HOME)/.cache/backend-slurm.jobid) 2>/dev/null || true; rm -f $(HOME)/.cache/backend-slurm.jobid; echo "backend Slurm job cancelled"; fi
	rm -f $(HOME)/.cache/backend-wake.need
	pkill -f "ssh.*-L 8000" 2>/dev/null || true
	pkill -f "vite.*5173" 2>/dev/null || true
	pkill -f "ngrok http" 2>/dev/null || true

hpc-slurm-status:
	@echo "== hpc-slurm status =="
	@curl -s http://localhost:8000/api/health 2>&1 | grep -q '"status":"ok"' && echo "backend: UP (via tunnel)" || echo "backend: DOWN"
	@if [ -f $(HOME)/.cache/backend-slurm.jobid ]; then squeue -j $$(cat $(HOME)/.cache/backend-slurm.jobid) 2>&1 | head -5; else echo "backend job: none"; fi
	@ss -tlnp 2>/dev/null | grep -q ":5173" && echo "frontend: UP (5173)" || echo "frontend: DOWN"
	@curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q public_url && echo "ngrok: UP" || echo "ngrok: DOWN"

hpc-slurm-clean:
	rm -rf data/analysis.db data/analysis.db-shm data/analysis.db-wal
	rm -rf frontend/node_modules frontend/.svelte-kit

docker-backend:
	PROFILE=docker docker compose up --build backend

docker-frontend:
	PROFILE=docker docker compose up --build frontend

docker:
	PROFILE=docker docker compose up --build

docker-eval:
	PROFILE=docker bash scripts/eval.sh

docker-stop:
	docker compose stop 2>/dev/null || true
	pkill -f "ngrok http" 2>/dev/null || true

docker-status:
	@docker compose ps 2>&1 | head -20
	@curl -s http://localhost:8000/api/health 2>&1 | grep -q '"status":"ok"' && echo "backend: UP" || echo "backend: DOWN"

docker-clean:
	docker compose down -v --remove-orphans 2>/dev/null || true

NGROK_URL := $(shell curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["tunnels"][0]["public_url"] if d["tunnels"] else "")' 2>/dev/null)

ngrok:
	@if [ -n "$(NGROK_URL)" ]; then \
	  echo "ngrok already running: $(NGROK_URL)"; \
	else \
	  nohup ngrok http 5173 > /tmp/ngrok.log 2>&1 & \
	  sleep 6; \
	  echo "ngrok started: $$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["tunnels"][0]["public_url"])')"; \
	fi

ngrok-stop:
	pkill -f "ngrok http" 2>/dev/null || true
	@echo "ngrok stopped"

ngrok-status:
	@if [ -n "$(NGROK_URL)" ]; then echo "ngrok: $(NGROK_URL)"; else echo "ngrok: DOWN"; fi

status: local-status hpc-status hpc-slurm-status docker-status
	@echo "All status checked"

stop: local-stop hpc-stop hpc-slurm-stop docker-stop ngrok-stop
	@echo "All stopped"

clean: local-clean hpc-clean hpc-slurm-clean docker-clean
	rm -rf frontend/node_modules frontend/.svelte-kit

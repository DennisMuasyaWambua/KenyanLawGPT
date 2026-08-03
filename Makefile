SHELL := /bin/bash
GOPATH_BIN := $(shell go env GOPATH)/bin

.PHONY: up down logs certs migrate seed proto test test-integration ps

## Bring the whole platform up (certs -> build -> migrate happens in-compose).
up: certs
	docker compose up -d --build
	@echo ""
	@echo "WakiliAI is starting:"
	@echo "  frontend   http://localhost:3000"
	@echo "  gateway    http://localhost:8080/healthz"
	@echo "  ai health  http://localhost:8081/healthz"
	@echo "  minio      http://localhost:59001 (minioadmin/minioadmin)"
	@echo "  neo4j      http://localhost:7474  (neo4j/wakili-neo4j)"
	@echo ""
	@echo "Next: make seed   (creates the two demo firms)"

down:
	docker compose down

logs:
	docker compose logs -f gateway ai

ps:
	docker compose ps

certs:
	bash infra/certs/gen-certs.sh

migrate:
	docker compose run --rm migrate

seed:
	docker compose --profile tools run --rm seed

## Regenerate gRPC stubs for both languages from /proto.
proto:
	PATH="$$PATH:$(GOPATH_BIN)" .venv/bin/python -m grpc_tools.protoc -I proto \
	  --python_out=services/ai/gen --grpc_python_out=services/ai/gen \
	  --go_out=services/gateway/gen --go_opt=module=github.com/wakiliai/gateway/gen \
	  --go-grpc_out=services/gateway/gen --go-grpc_opt=module=github.com/wakiliai/gateway/gen \
	  proto/wakili/v1/*.proto

## Unit tests (no services needed): Go tenant-isolation/auth/rbac + Python builders/tenancy.
test:
	cd services/gateway && go test ./...
	cd services/ai && ../../.venv/bin/python -m pytest tests -q

## Cross-tenant leakage suite — needs the compose stack (postgres+neo4j) up.
test-integration:
	cd services/ai && WAKILI_INTEGRATION=1 \
	  DATABASE_URL=postgresql://wakili_app:wakili_app_pw@localhost:55432/wakili \
	  NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=wakili-neo4j \
	  ../../.venv/bin/python -m pytest tests/test_leakage_integration.py -v

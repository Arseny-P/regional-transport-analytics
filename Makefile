COMPOSE := docker compose

.PHONY: build run run-local stop-volumes stop tools fmt fmt-check vet lint test tidy migrate-up migrate-down migrate-status

build:
	$(COMPOSE) up -d --build
run:
	$(COMPOSE) up -d

run-local:
	$(MAKE) -C backend/orchestrator-service run

stop-volumes:
	$(COMPOSE) down --volumes

stop:
	$(COMPOSE) down

tools fmt fmt-check vet lint test tidy migrate-up migrate-down migrate-status:
	$(MAKE) -C backend/orchestrator-service $@

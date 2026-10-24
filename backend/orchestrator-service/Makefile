BIN := $(CURDIR)/bin



ENV_FILE ?= ../../.env

# Читать локальные настройки и передавать их запускаемым программам.
# Если .env отсутствует (например, в CI), продолжать без него.
-include $(ENV_FILE)
export

export GOBIN := $(BIN)


.PHONY: run build tools fmt fmt-check vet lint test migrate-up migrate-down migrate-status

run:
	go run ./cmd/app

build:
	go build -o bin/orchestrator$(EXE) ./cmd/app

tools:
	go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.14.0
	go install github.com/pressly/goose/v3/cmd/goose@v3.26.0

fmt:
	gofmt -w cmd config internal

fmt-check:
	@files="$$(gofmt -l cmd config internal)" || exit $$?; \
	if [ -n "$$files" ]; then \
		printf '%s\n' "$$files"; \
		exit 1; \
	fi

vet:
	go vet ./...

lint:
	"$(BIN)/golangci-lint$(EXE)" run ./...
tidy:
	go mod tidy
test:
	go test -race -timeout 60s ./...

migrate-up:
	"$(BIN)/goose" -env "$(ENV_FILE)" -dir migrations up

migrate-down:
	"$(BIN)/goose" -env "$(ENV_FILE)" -dir migrations down

migrate-status:
	"$(BIN)/goose" -env "$(ENV_FILE)" -dir migrations status

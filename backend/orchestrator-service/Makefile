LOCAL_BIN := $(CURDIR)/bin
GOLANGCI_LINT:=$(LOCAL_BIN)/golangci-lint

export GOBIN := $(LOCAL_BIN)

bin-deps:
	go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@latest


govet:
	go vet ./...

golint:
	$(GOLANGCI_LINT) run ./...
	


tidy:
	go mod tidy

test:
	go test -v -race -timeout 60s ./...


cover:
	go test -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out

.PHONY: bin-deps buf-generate generate tidy test cover
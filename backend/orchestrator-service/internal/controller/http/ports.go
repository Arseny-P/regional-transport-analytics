package httpcontroller

import (
	"context"
	"orchestrator-service/internal/domain"

	"github.com/google/uuid"
)

type UsecaseOrchestrator interface {
	CreateJob(context.Context, uuid.UUID, uuid.UUID, float32, float32, float32, float32, []domain.Transport) (domain.JobStatus, bool, error)
}

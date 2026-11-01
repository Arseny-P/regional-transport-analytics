package usecase

import (
	"context"
	"orchestrator-service/internal/domain"
	miniodto "orchestrator-service/internal/dto/minio"

	"github.com/google/uuid"
)

type JobRepository interface {
	GetRegionInfo(context.Context, uuid.UUID) (domain.ObjectKey, error)
	GetJob(context.Context, uuid.UUID) (domain.Job, error)
	CreateJob(context.Context, *domain.Job) error
}

type MinIO interface {
	StatObject(context.Context, domain.ObjectKey) error
	GetObject(context.Context, domain.ObjectKey) (miniodto.Region, error)
}

type KafkaProducer interface {
	WriteMessage(context.Context, *domain.OutboxMessage) error
}

type OutboxRepository interface {
	GetMessages(context.Context, []uuid.UUID) ([]domain.OutboxMessage, error)
	SetReadyOutboxMessage(context.Context, uuid.UUID) error
}

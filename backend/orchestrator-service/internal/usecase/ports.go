package usecase

import (
	"context"
	"orchestrator-service/internal/domain"
	miniodto "orchestrator-service/internal/dto/minio"

	"github.com/google/uuid"
	"github.com/segmentio/kafka-go"
)

type JobRepository interface {
	GetJob(context.Context, uuid.UUID) (domain.Job, error)
	GetAnalysisResult(context.Context, uuid.UUID) (domain.AnalysisResult, error)
	CreateJob(context.Context, *domain.Job) error
	RequestJobCancellation(context.Context, uuid.UUID) (domain.JobStatus, error)
}

type RegionRepository interface {
	GetRegionInfo(context.Context, uuid.UUID) (domain.ObjectKey, error)
	CreateRegionInfo(context.Context, domain.ObjectKey, uuid.UUID) error
	GetRegionsInfo(context.Context) ([]domain.RegionRecord, error)
}

type MinIO interface {
	StatObject(context.Context, domain.ObjectKey) error
	GetObject(context.Context, domain.ObjectKey) (miniodto.Region, error)
	FPutObject(context.Context, domain.ObjectKey, string) error
	RemoveObject(context.Context, domain.ObjectKey) error
}

type KafkaOutboxProducer interface {
	WriteOutboxMessage(context.Context, *domain.OutboxMessage) error
}

type KafkaDLQProducer interface {
	WriteDLQMessage(context.Context, *domain.DLQMessage) error
}

type OutboxRepository interface {
	GetOutboxMessages(context.Context, []uuid.UUID) ([]domain.OutboxMessage, error)
	SetReadyOutboxMessage(context.Context, uuid.UUID) error
}

type InboxRepository interface {
	CreateAnalysisRes(context.Context, *domain.InboxMessage) error
}

type KafkaConsumer interface {
	FetchMessage(context.Context) (domain.InboxMessage, kafka.Message, error)
	CommitMessage(context.Context, *kafka.Message) error
}

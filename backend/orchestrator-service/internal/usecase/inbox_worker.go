package usecase

import (
	"context"
	"errors"
	"log/slog"
	"orchestrator-service/internal/domain"
	"time"

	"github.com/google/uuid"
	"github.com/segmentio/kafka-go"
)

type InboxWorker struct {
	kafkaConsumer   KafkaConsumer
	kafkaProducer   KafkaDLQProducer
	inboxRepository InboxRepository
	logger          *slog.Logger
}

func NewInboxWorker(kafkaConsumer KafkaConsumer, inboxRepository InboxRepository, kafkaProducer KafkaDLQProducer, logger *slog.Logger) *InboxWorker {
	return &InboxWorker{
		kafkaConsumer:   kafkaConsumer,
		kafkaProducer:   kafkaProducer,
		inboxRepository: inboxRepository,
		logger:          logger,
	}
}

func (iw *InboxWorker) Run(ctx context.Context) {

	message := struct {
		inboxMessage domain.InboxMessage
		kafkaMessage kafka.Message
		status       string
	}{}
	dlqMessage := domain.DLQMessage{}
	for {

		if ctx.Err() != nil {
			return
		}
		var err error

		if message.status == "" {
			message.inboxMessage, message.kafkaMessage, err = iw.kafkaConsumer.FetchMessage(ctx)
			if err != nil {
				if errors.Is(err, domain.ErrInvalidKafkaMessage) {
					message.status = "DLQ_PENDING"
					dlqMessage = newDLQMessage(&message.kafkaMessage, err)
					continue
				}
				iw.logger.ErrorContext(ctx, "failed to fetch", "error", err)
				if !Wait(ctx, 500*time.Millisecond) {
					return
				}
				continue
			}
			message.status = "FETCHED"
		}

		if message.status == "DLQ_PENDING" {
			dlqErr := iw.kafkaProducer.WriteDLQMessage(ctx, &dlqMessage)
			if dlqErr != nil {
				iw.logger.ErrorContext(ctx, "failed to write message to DLQ", "error", dlqErr)
				if !Wait(ctx, 500*time.Millisecond) {
					return
				}
				continue
			}

			message.status = "COMMIT_PENDING"
		} else if message.status == "FETCHED" {
			createAnalysisErr := iw.inboxRepository.CreateAnalysisRes(ctx, &message.inboxMessage)
			if createAnalysisErr != nil {
				if errors.Is(createAnalysisErr, domain.ErrJobNotFound) {
					dlqMessage = newDLQMessage(&message.kafkaMessage, createAnalysisErr)
					message.status = "DLQ_PENDING"
					continue
				}
				iw.logger.ErrorContext(ctx, "failed to create analysis Res", "error", createAnalysisErr)
				if !Wait(ctx, 250*time.Millisecond) {
					return
				}
				continue
			}
			message.status = "COMMIT_PENDING"
		}

		err = iw.kafkaConsumer.CommitMessage(ctx, &message.kafkaMessage)

		if err != nil {
			iw.logger.ErrorContext(ctx, "failed to commit message", "error", err)
			if !Wait(ctx, 200*time.Millisecond) {
				return
			}
			continue
		}

		message = struct {
			inboxMessage domain.InboxMessage
			kafkaMessage kafka.Message
			status       string
		}{}
		dlqMessage = domain.DLQMessage{}
	}

}

func newDLQMessage(message *kafka.Message, err error) domain.DLQMessage {
	dlq := domain.DLQMessage{
		Key: message.Key, Topic: message.Topic, Partition: message.Partition,
		Offset: message.Offset, Payload: message.Value, Error: err.Error(),
	}
	if jobID, parseErr := uuid.ParseBytes(message.Key); parseErr == nil && jobID != uuid.Nil {
		dlq.JobID = &jobID
	}
	return dlq
}

func Wait(ctx context.Context, duration time.Duration) bool {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

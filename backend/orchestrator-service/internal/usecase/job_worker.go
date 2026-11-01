package usecase

import (
	"context"
	"hash/crc32"
	"log/slog"
	"orchestrator-service/internal/domain"
	"sync"
	"time"

	"github.com/google/uuid"
)

type JobWorker struct {
	chSlice          []chan domain.OutboxMessage
	kafkaProducer    KafkaProducer
	outboxRepository OutboxRepository
	logger           *slog.Logger
}

type retryMessage struct {
	time    *time.Time
	message domain.OutboxMessage
}

func NewJobWorker(producer KafkaProducer, store OutboxRepository, logger *slog.Logger) *JobWorker {
	channels := make([]chan domain.OutboxMessage, 5)
	for i := range channels {
		channels[i] = make(chan domain.OutboxMessage, 5)
	}
	return &JobWorker{
		chSlice:          channels,
		kafkaProducer:    producer,
		outboxRepository: store,
		logger:           logger,
	}
}

func (jw *JobWorker) Run(ctx context.Context) {

	mu := &sync.Mutex{}
	m := make(map[string]retryMessage)
	handleMessage := func(message domain.OutboxMessage) {
		var err error
		for try := 1; try <= 5; try++ {
			if ctx.Err() != nil {
				return
			}
			err = jw.kafkaProducer.WriteMessage(ctx, &message)
			if err != nil {
				jw.logger.DebugContext(ctx, "Kafka send attempt failed",
					"job_id", message.JobID, "message_id", message.ID,
					"command_type", message.CommandType, "attempt", try, "error", err)
				if !waitContext(ctx, 500*time.Millisecond+time.Duration(2*try)*100*time.Millisecond) {
					return
				}

				continue
			}
			break

		}

		addJobToMap := func() {
			mu.Lock()
			timeElapsed := time.Now().Add(1 * time.Second)
			m[message.JobID.String()] = retryMessage{
				time:    &timeElapsed,
				message: message,
			}
			mu.Unlock()
		}
		if err != nil {
			jw.logger.WarnContext(ctx, "Kafka send failed; scheduling retry",
				"job_id", message.JobID, "message_id", message.ID,
				"command_type", message.CommandType, "error", err)
			addJobToMap()
			return

		}

		err = jw.outboxRepository.SetReadyOutboxMessage(ctx, message.ID)

		if err != nil {
			jw.logger.WarnContext(ctx, "outbox READY update failed; scheduling retry",
				"job_id", message.JobID, "message_id", message.ID,
				"command_type", message.CommandType, "error", err)
			addJobToMap()
			return
		}

		mu.Lock()
		delete(m, message.JobID.String())
		mu.Unlock()
		jw.logger.InfoContext(ctx, "outbox command delivered",
			"job_id", message.JobID, "message_id", message.ID, "command_type", message.CommandType)
	}
	var workers sync.WaitGroup
	defer workers.Wait()
	for i := 0; i < len(jw.chSlice); i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			jw.runShard(ctx, i, mu, m, handleMessage)
		}()
	}

	slice := make([]uuid.UUID, 0)
	for {
		if ctx.Err() != nil {
			return
		}
		mu.Lock()
		for _, item := range m {
			slice = append(slice, item.message.JobID)
		}

		mu.Unlock()
		messages, err := jw.outboxRepository.GetMessages(ctx, slice)
		slice = slice[:0]
		if ctx.Err() != nil {
			return
		}
		if err != nil {
			jw.logger.ErrorContext(ctx, "failed to read outbox", "error", err)
		}
		if err != nil || len(messages) == 0 {
			if !waitContext(ctx, time.Second) {
				return
			}
			continue
		}

		for _, message := range messages {
			mu.Lock()
			_, ok := m[message.JobID.String()]
			if ok {
				mu.Unlock()
				continue
			}

			m[message.JobID.String()] = retryMessage{
				message: message,
			}

			mu.Unlock()
			shard := crc32.ChecksumIEEE(message.JobID[:]) % uint32(len(jw.chSlice))
			select {
			case <-ctx.Done():
				return
			case jw.chSlice[shard] <- message:
			}
		}

	}
}

func (jw *JobWorker) runShard(ctx context.Context, shard int, mu *sync.Mutex,
	pending map[string]retryMessage, handleMessage func(domain.OutboxMessage)) {
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case message := <-jw.chSlice[shard]:
			handleMessage(message)
		case <-ticker.C:
			mu.Lock()
			var message domain.OutboxMessage
			var found bool
			for _, item := range pending {
				messageShard := crc32.ChecksumIEEE(item.message.JobID[:]) % uint32(len(jw.chSlice))
				if messageShard != uint32(shard) {
					continue
				}
				if item.time != nil && !time.Now().Before(*item.time) {
					message = item.message
					found = true
					break
				}
			}
			mu.Unlock()
			if found {
				handleMessage(message)
			}
		}
	}
}

func waitContext(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

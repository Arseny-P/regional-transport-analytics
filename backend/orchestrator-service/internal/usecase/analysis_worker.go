package usecase

import (
	"context"
	"errors"
	"log/slog"
	"orchestrator-service/internal/domain"
	"sync"
	"time"

	"github.com/google/uuid"
)

type AnalysisWorker struct {
	jobsHeartbeats map[string]domain.Heartbeat
	semaphore      chan struct{}
	mu             *sync.Mutex
	jobRepository  JobRepository
	logger         *slog.Logger
	wg             *sync.WaitGroup
}

func NewAnalysisWorker(jobRepository JobRepository, logger *slog.Logger) *AnalysisWorker {
	return &AnalysisWorker{
		jobsHeartbeats: make(map[string]domain.Heartbeat),
		mu:             &sync.Mutex{},
		jobRepository:  jobRepository,
		semaphore:      make(chan struct{}, 5),
		logger:         logger,
		wg:             &sync.WaitGroup{},
	}
}

func (aw *AnalysisWorker) UpdateHeartbeat(jobID uuid.UUID, receivedAt, deadline time.Time) error {
	aw.mu.Lock()
	val, ok := aw.jobsHeartbeats[jobID.String()]
	heartbeatExpired := ok && receivedAt.After(val.Time)
	if !heartbeatExpired {
		if !deadline.Before(val.Time) {
			aw.jobsHeartbeats[jobID.String()] = domain.Heartbeat{
				Time: deadline,
			}
		}

	}

	aw.mu.Unlock()
	if heartbeatExpired {
		return domain.ErrHeartbeatTimeoutExceeded
	}

	return nil

}

func (aw *AnalysisWorker) GetHeartbeatResponse(ctx context.Context, jobID uuid.UUID) (domain.HeartbeatResponse, error) {
	result, err := aw.jobRepository.GetAnalysisResult(ctx, jobID)
	if err != nil {
		return domain.HeartbeatResponse{}, err
	}

	response := domain.HeartbeatResponse{
		Status:           result.Payload.Status,
		GraphAvailable:   result.GraphAvailable,
		MetricsAvailable: result.MetricsAvailable,
		Error:            result.Payload.Error,
	}

	if result.Payload.Status != "queued" && result.Payload.Status != "running" {
		aw.mu.Lock()
		delete(aw.jobsHeartbeats, jobID.String())
		aw.mu.Unlock()
	}

	return response, nil
}

func (aw *AnalysisWorker) Run(ctx context.Context) {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			aw.CheckInactiveJobs(ctx)
		case <-ctx.Done():
			aw.wg.Wait()
			return
		}
	}
}

func (aw *AnalysisWorker) CheckInactiveJobs(ctx context.Context) {
	aw.mu.Lock()
	canceledJobs := make([]uuid.UUID, 0)
	for key, val := range aw.jobsHeartbeats {
		if !time.Now().After(val.Time) || val.Status == "PENDING" {
			continue
		}
		id, err := uuid.Parse(key)
		if err != nil {
			aw.logger.ErrorContext(ctx, "failed to parse jobId string", "error", err)
			continue
		}
		val.Status = "PENDING"
		aw.jobsHeartbeats[key] = val
		canceledJobs = append(canceledJobs, id)
	}

	if ctx.Err() != nil {
		aw.mu.Unlock()
		return
	}
	aw.wg.Add(1)
	go func() {
		defer aw.wg.Done()
		for _, id := range canceledJobs {

			select {
			case aw.semaphore <- struct{}{}:
				aw.wg.Add(1)

			case <-ctx.Done():
				return
			}

			go func() {
				defer func() {
					<-aw.semaphore
					aw.wg.Done()
				}()

				if ctx.Err() != nil {
					return
				}
				_, err := aw.jobRepository.RequestJobCancellation(ctx, id)
				if err != nil {
					if errors.Is(err, context.Canceled) {
						aw.logger.ErrorContext(ctx, "context is canceled", "error", err)
						return
					}
					aw.mu.Lock()
					aw.jobsHeartbeats[id.String()] = domain.Heartbeat{
						Time:   aw.jobsHeartbeats[id.String()].Time,
						Status: "",
					}
					aw.mu.Unlock()
					aw.logger.ErrorContext(ctx, "failed to req job cancellations", "error", err)
					return
				}
				aw.mu.Lock()
				delete(aw.jobsHeartbeats, id.String())
				aw.mu.Unlock()

			}()
			// тут нужны транзакции на каждую job я вижу это так мб неоптимально но хз если честно типо нужен update и запись в outbox ток дело в дублировании кода в целом мозешь в postgres вынести функции эти отдельные и с тра
			// нзакцией как то связать или не бля
		}

	}()

	aw.mu.Unlock()

}

// касаемо вот это типо писать надо в одной транзакции и апдейт и в outbox и получается дерьмо поскольку долго нутипо если будем стопариться так то такое сбебе я думаю удалить и перенсти
// в другое место ну просто в слайс мб эти элементы откуда отдельная функция будет писать уже и всё)

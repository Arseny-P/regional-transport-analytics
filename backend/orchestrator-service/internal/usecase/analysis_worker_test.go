package usecase

import (
	"context"
	"log/slog"
	"orchestrator-service/internal/domain"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestAnalysisWorker(t *testing.T) {
	id := uuid.New()
	analysisResult := domain.AnalysisResult{
		JobID:            id,
		GraphAvailable:   true,
		MetricsAvailable: true,
		Payload: domain.AnalysisPayload{
			Status: "running",
		},
	}
	heartbeatResponse := domain.HeartbeatResponse{
		Status:           "running",
		GraphAvailable:   true,
		MetricsAvailable: true,
	}
	testTable := []struct {
		TestName               string
		HasHeartbeat           bool
		InitialDeadlineOffset  time.Duration
		ReceivedAtOffset       time.Duration
		ExpectedDeadlineOffset time.Duration
		AnalysisRes            domain.AnalysisResult
		ExpectedHeartbeatRes   domain.HeartbeatResponse
		AnalysisErr            error
		ExpectedHeartbeatErr   error
	}{
		{
			TestName:               "Первый heartbeat добавляет дедлайн",
			ExpectedDeadlineOffset: 10 * time.Second,
			AnalysisRes:            analysisResult,
			ExpectedHeartbeatRes:   heartbeatResponse,
		},
		{
			TestName:               "Своевременный heartbeat продлевает дедлайн",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  10 * time.Second,
			ReceivedAtOffset:       5 * time.Second,
			ExpectedDeadlineOffset: 15 * time.Second,
			AnalysisRes:            analysisResult,
			ExpectedHeartbeatRes:   heartbeatResponse,
		},
		{
			TestName:               "Старый heartbeat не уменьшает дедлайн",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  15 * time.Second,
			ReceivedAtOffset:       2 * time.Second,
			ExpectedDeadlineOffset: 15 * time.Second,
			AnalysisRes:            analysisResult,
			ExpectedHeartbeatRes:   heartbeatResponse,
		},
		{
			TestName:               "Heartbeat пришёл вовремя, но обрабатывается после дедлайна",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  -time.Second,
			ReceivedAtOffset:       -2 * time.Second,
			ExpectedDeadlineOffset: 8 * time.Second,
			AnalysisRes:            analysisResult,
			ExpectedHeartbeatRes:   heartbeatResponse,
		},
		{
			TestName:               "Просроченный heartbeat возвращает таймаут и данные задачи",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  10 * time.Second,
			ReceivedAtOffset:       11 * time.Second,
			ExpectedDeadlineOffset: 10 * time.Second,
			AnalysisRes:            analysisResult,
			ExpectedHeartbeatRes: domain.HeartbeatResponse{
				Status:           "running",
				GraphAvailable:   true,
				MetricsAvailable: true,
			},
			ExpectedHeartbeatErr: domain.ErrHeartbeatTimeoutExceeded,
		},
		{
			TestName:               "Heartbeat ровно на дедлайне принимается",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  10 * time.Second,
			ReceivedAtOffset:       10 * time.Second,
			ExpectedDeadlineOffset: 20 * time.Second,
			AnalysisRes:            analysisResult,
			ExpectedHeartbeatRes:   heartbeatResponse,
		},
		{
			TestName:               "Задача не найдена",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  10 * time.Second,
			ReceivedAtOffset:       5 * time.Second,
			ExpectedDeadlineOffset: 15 * time.Second,
			AnalysisErr:            domain.ErrJobNotFound,
		},
		{
			TestName:               "Ошибка чтения задачи из БД",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  10 * time.Second,
			ReceivedAtOffset:       5 * time.Second,
			ExpectedDeadlineOffset: 15 * time.Second,
			AnalysisErr:            domain.ErrInternalDB,
		},
		{
			TestName:               "Старый heartbeat не уменьшает дедлайн",
			HasHeartbeat:           true,
			InitialDeadlineOffset:  15 * time.Second,
			ReceivedAtOffset:       10 * time.Second,
			ExpectedDeadlineOffset: 20 * time.Second,
			AnalysisRes: domain.AnalysisResult{
				JobID:            id,
				GraphAvailable:   true,
				MetricsAvailable: true,
				Payload: domain.AnalysisPayload{
					Status: "completed",
				},
			},
			ExpectedHeartbeatRes: domain.HeartbeatResponse{
				Status:           "completed",
				GraphAvailable:   true,
				MetricsAvailable: true,
			},
		},
	}

	for _, tt := range testTable {
		t.Run(tt.TestName, func(t *testing.T) {
			mockJobRep := MockJobRepository{
				analysisRes: tt.AnalysisRes,
				analysisErr: tt.AnalysisErr,
			}

			analysisWorker := NewAnalysisWorker(&mockJobRep, slog.Default())
			ctx, cancel := context.WithCancel(context.Background())
			now := time.Now()
			if tt.HasHeartbeat {
				require.NoError(t, analysisWorker.UpdateHeartbeat(id, now, now.Add(tt.InitialDeadlineOffset)))
			}
			receivedAt := now.Add(tt.ReceivedAtOffset)
			heartbeatErr := analysisWorker.UpdateHeartbeat(id, receivedAt, receivedAt.Add(10*time.Second))
			finished := make(chan struct{})
			go func() {
				defer close(finished)
				analysisWorker.Run(ctx)
			}()
			t.Cleanup(func() {
				cancel()
				select {
				case <-finished:
				case <-time.After(5 * time.Second):
					t.Error("Воркер не завершился после отмены контекста")
				}
			})

			res, err := analysisWorker.GetHeartbeatResponse(ctx, id)
			if tt.AnalysisErr != nil {
				require.ErrorIs(t, err, tt.AnalysisErr)
			} else {
				require.NoError(t, err)
			}
			if tt.ExpectedHeartbeatErr != nil {
				require.ErrorIs(t, heartbeatErr, tt.ExpectedHeartbeatErr)
			} else {
				require.NoError(t, heartbeatErr)
			}
			assert.Equal(t, tt.ExpectedHeartbeatRes, res)

			switch tt.ExpectedHeartbeatRes.Status {
			case "canceled", "failed", "completed", "cancel_requested":
				require.Eventually(t, func() bool {
					analysisWorker.mu.Lock()
					_, ok := analysisWorker.jobsHeartbeats[id.String()]
					analysisWorker.mu.Unlock()
					return !ok
				}, 5*time.Second, 500*time.Millisecond)
				return
			}
			analysisWorker.mu.Lock()
			heartbeat, ok := analysisWorker.jobsHeartbeats[id.String()]
			analysisWorker.mu.Unlock()
			require.True(t, ok)
			assert.Equal(t, now.Add(tt.ExpectedDeadlineOffset), heartbeat.Time)
		})
	}
}

func TestCheckInactiveJobsRetry(t *testing.T) {
	id := uuid.New()
	mockJobRep := MockJobRepository{
		cancelErr:    domain.ErrInternalDB,
		cancelStatus: "cancel_requested",
	}
	analysisWorker := NewAnalysisWorker(&mockJobRep, slog.Default())
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(func() {
		cancel()
		analysisWorker.wg.Wait()
	})

	now := time.Now()
	deadline := now.Add(-time.Second)
	require.NoError(t, analysisWorker.UpdateHeartbeat(id, now, deadline))

	analysisWorker.CheckInactiveJobs(ctx)
	require.Eventually(t, func() bool {
		analysisWorker.mu.Lock()
		defer analysisWorker.mu.Unlock()
		heartbeat, ok := analysisWorker.jobsHeartbeats[id.String()]
		return ok && heartbeat.Status == ""
	}, 5*time.Second, 10*time.Millisecond)

	analysisWorker.mu.Lock()
	heartbeat, ok := analysisWorker.jobsHeartbeats[id.String()]
	analysisWorker.mu.Unlock()
	require.True(t, ok)
	assert.Equal(t, deadline, heartbeat.Time)
	assert.Empty(t, heartbeat.Status)

	analysisWorker.CheckInactiveJobs(ctx)
	require.Eventually(t, func() bool {
		analysisWorker.mu.Lock()
		defer analysisWorker.mu.Unlock()
		_, ok := analysisWorker.jobsHeartbeats[id.String()]
		return !ok
	}, 5*time.Second, 10*time.Millisecond)
}

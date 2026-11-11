package httpcontroller

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"orchestrator-service/internal/domain"
	httpdto "orchestrator-service/internal/dto/http"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type MockJobUsecase struct {
	result  domain.AnalysisResult
	pending bool
	err     error
}

func (mockU *MockJobUsecase) GetAnalysisResult(context.Context, uuid.UUID) (domain.AnalysisResult, error) {
	return mockU.result, mockU.err
}

func (mockU *MockJobUsecase) CancelJob(context.Context, uuid.UUID) (domain.AnalysisResult, bool, error) {
	return mockU.result, mockU.pending, mockU.err
}

func (mockU *MockJobUsecase) CreateJob(context.Context, uuid.UUID, uuid.UUID, float64, float64, float64, float64, []domain.Transport) (domain.JobStatus, bool, error) {
	panic("unexpected CreateJob call")
}

type MockHeartbeatWorker struct {
	response            domain.HeartbeatResponse
	responseErr         error
	heartbeatTimeOutErr error
}

func (mockW *MockHeartbeatWorker) GetHeartbeatResponse(context.Context, uuid.UUID) (domain.HeartbeatResponse, error) {
	return mockW.response, mockW.responseErr
}

func (mockW *MockHeartbeatWorker) UpdateHeartbeat(uuid.UUID, time.Time, time.Time) error {
	return mockW.heartbeatTimeOutErr
}

func TestSendAnalysisHeartbeatHandler(t *testing.T) {
	id := uuid.New()
	tableTests := []struct {
		TestName              string
		JobID                 string
		ExpectedCode          int
		ExpectedResp          httpdto.AnalysisStatus
		ExpectedErrorResponse *httpdto.Error
		DomainResponse        domain.HeartbeatResponse
		ResponseErr           error
		ErrTimeOutHeartbeat   error
		ContextIsCanceled     bool
	}{
		{
			TestName:     "Задача в очереди",
			JobID:        id.String(),
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.Queued,
			},
			DomainResponse: domain.HeartbeatResponse{Status: "queued"},
		},
		{
			TestName:     "Задача выполняется, граф доступен",
			JobID:        id.String(),
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.Running,
				GraphAvailable: true,
			},
			DomainResponse: domain.HeartbeatResponse{
				Status: "running", GraphAvailable: true,
			},
		},
		{
			TestName:     "Задача завершена",
			JobID:        id.String(),
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.Completed,
				GraphAvailable:   true,
				MetricsAvailable: true,
			},
			DomainResponse: domain.HeartbeatResponse{
				Status: "completed", GraphAvailable: true, MetricsAvailable: true,
			},
		},
		{
			TestName:     "Анализ завершился ошибкой",
			JobID:        id.String(),
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.Failed,
				GraphAvailable: true,
				Error: &httpdto.AnalysisFailure{
					Code: "metrics_calculation_failed", Message: "Не удалось рассчитать метрики",
				},
			},
			DomainResponse: domain.HeartbeatResponse{
				Status: "failed", GraphAvailable: true,
				Error: &domain.ErrorResp{
					Code: "metrics_calculation_failed", Message: "Не удалось рассчитать метрики",
				},
			},
		},
		{
			TestName:     "Отмена запрошена",
			JobID:        id.String(),
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.CancelRequested,
			},
			DomainResponse: domain.HeartbeatResponse{Status: "cancel_requested"},
		},
		{
			TestName:     "Задача отменена",
			JobID:        id.String(),
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.Canceled,
			},
			DomainResponse: domain.HeartbeatResponse{Status: "canceled"},
		},
		{
			TestName:     "Не передан job_id",
			ExpectedCode: http.StatusBadRequest,
			ExpectedErrorResponse: &httpdto.Error{
				Code: "missing_job_id", Field: "job_id", Message: "Укажи job_id в параметрах запроса",
			},
		},
		{
			TestName:     "Некорректный UUID",
			JobID:        "not-a-uuid",
			ExpectedCode: http.StatusBadRequest,
			ExpectedErrorResponse: &httpdto.Error{
				Code: "invalid_job_id", Field: "job_id", Message: "job_id должен быть UUID",
			},
		},
		{
			TestName:     "Задача не найдена",
			JobID:        id.String(),
			ExpectedCode: http.StatusNotFound,
			ResponseErr:  domain.ErrJobNotFound,
			ExpectedErrorResponse: &httpdto.Error{
				Code: "job_not_found", Field: "job_id", Message: "Задача не найдена",
			},
		},
		{
			TestName:     "Ошибка БД",
			JobID:        id.String(),
			ExpectedCode: http.StatusInternalServerError,
			ResponseErr:  domain.ErrInternalDB,
			ExpectedErrorResponse: &httpdto.Error{
				Code: "internal_db_error", Message: "Не удалось выполнить операцию с базой данных",
			},
		},
		{
			TestName:     "Внутренняя ошибка",
			JobID:        id.String(),
			ExpectedCode: http.StatusInternalServerError,
			ResponseErr:  domain.ErrInternalServer,
			ExpectedErrorResponse: &httpdto.Error{
				Code: "internal_error", Message: "Внутренняя ошибка сервера",
			},
		},
		{
			TestName:     "Пустой ответ воркера",
			JobID:        id.String(),
			ExpectedCode: http.StatusInternalServerError,
			ExpectedErrorResponse: &httpdto.Error{
				Code: "internal_error", Message: "Внутренняя ошибка сервера",
			},
		},
		{
			TestName:            "Таймаут хартбита и успешное чтение БД",
			JobID:               id.String(),
			ExpectedCode:        http.StatusOK,
			ErrTimeOutHeartbeat: domain.ErrHeartbeatTimeoutExceeded,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID:  id.String(),
				Status: "running",
				Error: &httpdto.AnalysisFailure{
					Code:    "heartbeat_timeout_exceeded",
					Message: "Heartbeat не поступал более 10 секунд. Срок подтверждения активности истёк",
				},
			},
			DomainResponse: domain.HeartbeatResponse{
				Status: "running",
			},
		},
		{
			TestName:            "Таймаут хартбита и ошибка БД",
			JobID:               id.String(),
			ExpectedCode:        http.StatusInternalServerError,
			ErrTimeOutHeartbeat: domain.ErrHeartbeatTimeoutExceeded,
			ExpectedErrorResponse: &httpdto.Error{
				Code:    "internal_db_error",
				Message: "Не удалось выполнить операцию с базой данных",
			},
			ResponseErr: domain.ErrInternalDB,
		},
		{
			TestName:          "Отменённый контекст heartbeat",
			JobID:             id.String(),
			ResponseErr:       context.Canceled,
			ContextIsCanceled: true,
		},
	}

	for _, tt := range tableTests {
		t.Run(tt.TestName, func(t *testing.T) {
			mockHW := MockHeartbeatWorker{
				response:            tt.DomainResponse,
				responseErr:         tt.ResponseErr,
				heartbeatTimeOutErr: tt.ErrTimeOutHeartbeat,
			}

			httpController := NewHTTPController(nil, nil, &mockHW, slog.Default())

			url := "/analysis/heartbeat"

			if tt.JobID != "" {
				url += "?job_id=" + tt.JobID
			}

			req := httptest.NewRequest(http.MethodPost, url, http.NoBody)
			recorder := httptest.NewRecorder()
			if tt.ContextIsCanceled {
				ctx, cancel := context.WithCancel(req.Context())
				cancel()
				req = req.WithContext(ctx)
			}

			httpController.SendAnalysisHeartbeatHandler().ServeHTTP(recorder, req)

			if tt.ContextIsCanceled {
				assert.Empty(t, recorder.Header().Get("Content-Type"))
				assert.Empty(t, recorder.Body.Bytes())
				return
			}
			require.Equal(t, tt.ExpectedCode, recorder.Code)
			require.Equal(t, "application/json", recorder.Header().Get("content-type"))
			if tt.ExpectedErrorResponse != nil {
				var errorBody httpdto.Error
				require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &errorBody))
				assert.Equal(t, *tt.ExpectedErrorResponse, errorBody)
				return
			}

			var body httpdto.AnalysisStatus
			require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &body))
			assert.Equal(t, tt.ExpectedResp, body)
		})
	}
}

func TestCancelAnalysisHandler(t *testing.T) {
	id := uuid.New()
	requestedResult := domain.AnalysisResult{
		JobID: id,
		Payload: domain.AnalysisPayload{
			Status: "cancel_requested",
		},
		GraphAvailable:   true,
		MetricsAvailable: true,
	}
	canceledResult := domain.AnalysisResult{
		JobID: id,
		Payload: domain.AnalysisPayload{
			Status: "canceled",
			Error: &domain.ErrorResp{
				Code: "analysis_canceled", Message: "Анализ отменён",
			},
		},
	}
	testTable := []struct {
		TestName          string
		JobID             string
		Result            domain.AnalysisResult
		Pending           bool
		UsecaseErr        error
		ExpectedCode      int
		ExpectedResp      httpdto.AnalysisStatus
		ExpectedErrorCode string
	}{
		{
			TestName:     "Отмена запрошена",
			JobID:        id.String(),
			Result:       requestedResult,
			Pending:      true,
			ExpectedCode: http.StatusAccepted,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.CancelRequested,
				GraphAvailable: true, MetricsAvailable: true,
			},
		},
		{
			TestName:     "Задача уже отменена",
			JobID:        id.String(),
			Result:       canceledResult,
			ExpectedCode: http.StatusOK,
			ExpectedResp: httpdto.AnalysisStatus{
				JobID: id.String(), Status: httpdto.Canceled,
				Error: &httpdto.AnalysisFailure{
					Code: "analysis_canceled", Message: "Анализ отменён",
				},
			},
		},
		{
			TestName:          "Не передан job_id",
			ExpectedCode:      http.StatusBadRequest,
			ExpectedErrorCode: "missing_job_id",
		},
		{
			TestName:          "Некорректный UUID",
			JobID:             "not-a-uuid",
			ExpectedCode:      http.StatusBadRequest,
			ExpectedErrorCode: "invalid_job_id",
		},
		{
			TestName:          "Задача не найдена",
			JobID:             id.String(),
			UsecaseErr:        domain.ErrJobNotFound,
			ExpectedCode:      http.StatusNotFound,
			ExpectedErrorCode: "job_not_found",
		},
		{
			TestName:          "Завершённую задачу нельзя отменить",
			JobID:             id.String(),
			UsecaseErr:        domain.ErrJobAlreadyFinished,
			ExpectedCode:      http.StatusConflict,
			ExpectedErrorCode: "job_already_finished",
		},
		{
			TestName: "Получен статус completed",
			JobID:    id.String(),
			Result: domain.AnalysisResult{
				JobID: id, Payload: domain.AnalysisPayload{Status: "completed"},
			},
			ExpectedCode:      http.StatusConflict,
			ExpectedErrorCode: "job_already_finished",
		},
		{
			TestName: "Получен статус failed",
			JobID:    id.String(),
			Result: domain.AnalysisResult{
				JobID: id, Payload: domain.AnalysisPayload{Status: "failed"},
			},
			ExpectedCode:      http.StatusConflict,
			ExpectedErrorCode: "job_already_finished",
		},
		{
			TestName:          "Ошибка БД",
			JobID:             id.String(),
			UsecaseErr:        domain.ErrInternalDB,
			ExpectedCode:      http.StatusInternalServerError,
			ExpectedErrorCode: "internal_db_error",
		},
		{
			TestName:          "Внутренняя ошибка",
			JobID:             id.String(),
			UsecaseErr:        domain.ErrInternalServer,
			ExpectedCode:      http.StatusInternalServerError,
			ExpectedErrorCode: "internal_error",
		},
	}

	for _, tt := range testTable {
		t.Run(tt.TestName, func(t *testing.T) {
			mockJobUsecase := MockJobUsecase{
				result:  tt.Result,
				pending: tt.Pending,
				err:     tt.UsecaseErr,
			}
			controller := NewHTTPController(&mockJobUsecase, nil, nil, slog.Default())
			url := "/analysis/cancel"
			if tt.JobID != "" {
				url += "?job_id=" + tt.JobID
			}
			request := httptest.NewRequest(http.MethodPost, url, http.NoBody)
			response := httptest.NewRecorder()
			controller.CancelAnalysisHandler().ServeHTTP(response, request)

			assert.Equal(t, tt.ExpectedCode, response.Code)
			assert.Equal(t, "application/json", response.Header().Get("Content-Type"))
			if tt.ExpectedErrorCode != "" {
				var body httpdto.Error
				require.NoError(t, json.Unmarshal(response.Body.Bytes(), &body))
				assert.Equal(t, tt.ExpectedErrorCode, body.Code)
				assert.NotEmpty(t, body.Message)
				if tt.ExpectedCode < http.StatusInternalServerError {
					assert.Equal(t, "job_id", body.Field)
				}
				return
			}

			var body httpdto.AnalysisStatus
			require.NoError(t, json.Unmarshal(response.Body.Bytes(), &body))
			assert.Equal(t, tt.ExpectedResp, body)
		})
	}
}

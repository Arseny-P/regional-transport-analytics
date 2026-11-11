package httpcontroller

import (
	"encoding/json"
	"log/slog"
	"net/http"
)

type HTTPController struct {
	jobUsecase      JobUsecase
	regionUsecase   RegionUsecase
	heartbeatWorker HeartbeatWorker
	logger          *slog.Logger
}

func NewHTTPController(jobUsecase JobUsecase, regionUsecase RegionUsecase, heartbeatWorker HeartbeatWorker, logger *slog.Logger) *HTTPController {
	return &HTTPController{
		jobUsecase:      jobUsecase,
		regionUsecase:   regionUsecase,
		heartbeatWorker: heartbeatWorker,
		logger:          logger,
	}
}

func (hc *HTTPController) WriteResponse(w http.ResponseWriter, code int, resp interface{}) {
	w.Header().Add("content-type", "application/json")
	w.WriteHeader(code)
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		hc.logger.Warn("failed to write HTTP response", "status", code, "error", err)
	}
}

package httpcontroller

import (
	"encoding/json"
	"log/slog"
	"net/http"
)

type HTTPController struct {
	usecaseOrchestrator UsecaseOrchestrator
	logger              *slog.Logger
}

func NewHTTPController(usecaseOrchestrator UsecaseOrchestrator, logger *slog.Logger) *HTTPController {
	return &HTTPController{
		usecaseOrchestrator: usecaseOrchestrator,
		logger:              logger,
	}
}

func (hc *HTTPController) WriteResponse(w http.ResponseWriter, code int, resp interface{}) {
	w.Header().Add("content-type", "application/json")
	w.WriteHeader(code)
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		hc.logger.Warn("failed to write HTTP response", "status", code, "error", err)
	}
}

package kafkadto

import (
	"orchestrator-service/internal/dto"

	"github.com/google/uuid"
)

type InboxMessage struct {
	MessageID uuid.UUID       `json:"message_id"`
	JobID     uuid.UUID       `json:"job_id"`
	Type      string          `json:"type"`
	Payload   AnalysisPayload `json:"payload"`
}

type AnalysisPayload struct {
	Status  string       `json:"status"`
	Graph   *dto.Graph   `json:"graph,omitempty"`
	Metrics []dto.Metric `json:"metrics,omitempty"`
	Error   *ErrorResp   `json:"error,omitempty"`
}

type ErrorResp struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

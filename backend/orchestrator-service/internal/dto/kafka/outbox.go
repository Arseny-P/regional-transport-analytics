package kafkadto

import (
	"orchestrator-service/internal/dto"

	"github.com/google/uuid"
)

type OutboxMessage struct {
	MessageID uuid.UUID      `json:"message_id"`
	JobID     uuid.UUID      `json:"job_id"`
	Type      string         `json:"type"`
	Payload   CommandPayload `json:"payload"`
}

type CommandPayload struct {
	Area       *Area    `json:"area,omitempty"`
	Transports []string `json:"transports,omitempty"`
}

type Area = dto.AnalysisArea

type MapPoint = dto.MapPoint

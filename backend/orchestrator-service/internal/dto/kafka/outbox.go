package kafkadto

import "github.com/google/uuid"

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

type Area struct {
	FirstPoint  MapPoint `json:"first_point"`
	SecondPoint MapPoint `json:"second_point"`
}

type MapPoint struct {
	Latitude  float32 `json:"latitude"`
	Longitude float32 `json:"longitude"`
}

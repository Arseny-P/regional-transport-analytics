package kafkadto

import (
	"github.com/google/uuid"
)

type DLQMessage struct {
	JobID     *uuid.UUID `json:"job_id,omitempty"`
	Key       []byte     `json:"key"`
	Topic     string     `json:"topic"`
	Partition int        `json:"partition"`
	Offset    int64      `json:"offset"`
	Payload   []byte     `json:"payload"`
	Error     string     `json:"error"`
}

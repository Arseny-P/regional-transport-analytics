package domain

import (
	"time"

	"github.com/google/uuid"
)

type DLQMessage struct {
	JobID     *uuid.UUID
	Key       []byte
	Topic     string
	Partition int
	Offset    int64
	Payload   []byte
	Error     string
}

type OutboxMessage struct {
	ID             uuid.UUID
	JobID          uuid.UUID
	CommandType    string
	TransportTypes []Transport
	Point1         MapPoint
	Point2         MapPoint
}

type InboxMessage struct {
	MessageID     uuid.UUID
	JobID         uuid.UUID
	TransportType Transport
	Type          string
	Payload       AnalysisPayload
}

type AnalysisPayload struct {
	Status  JobStatus
	Graph   *Graph
	Metrics []Metric
	Error   *ErrorResp
}

type WorksRes struct {
	Payload          AnalysisPayload
	GraphAvailable   bool
	TransportType    Transport
	MetricsAvailable bool
}

type AnalysisResult struct {
	JobID       uuid.UUID
	Payload     AnalysisPayload
	WorkResults []*WorksRes
}

type Graph struct {
	Nodes []GraphNode
	Edges []GraphEdge
}

type GraphNode struct {
	ID         string
	Position   []float64
	Attributes map[string]any
}

type GraphEdge struct {
	ID         string
	SegmentID  *string
	Source     string
	Target     string
	Geometry   [][]float64
	Attributes map[string]any
}

type Metric struct {
	NodeID *string
	Name   string
	Value  float32
}

type ErrorResp struct {
	Code    string
	Message string
}

type Heartbeat struct {
	Time   time.Time
	Status string
}
type HeartbeatResponse struct {
	Status      JobStatus
	WorkResults []*WorksRes
}

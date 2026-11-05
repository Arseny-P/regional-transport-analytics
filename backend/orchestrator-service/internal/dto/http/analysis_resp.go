package httpdto

import "orchestrator-service/internal/dto"

const (
	CancelRequested JobState = "cancel_requested"
	Canceled        JobState = "canceled"
	Completed       JobState = "completed"
	Failed          JobState = "failed"
	Queued          JobState = "queued"
	Running         JobState = "running"
)

type JobState string

type AnalysisStatus struct {
	Error *AnalysisFailure `json:"error,omitempty"`

	GraphAvailable bool `json:"graph_available"`

	JobID Identifier `json:"job_id"`

	MetricsAvailable bool `json:"metrics_available"`

	Status JobState `json:"status"`
}

type JobStatus = AnalysisStatus

type AnalysisResult struct {
	Error *AnalysisFailure `json:"error,omitempty"`
	Graph *Graph           `json:"graph"`

	GraphAvailable bool `json:"graph_available"`

	JobID Identifier `json:"job_id"`

	Metrics Metrics `json:"metrics"`

	MetricsAvailable bool `json:"metrics_available"`

	Status JobState `json:"status"`
}

type AnalysisFailure struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type AnalysisReceipt struct {
	JobID Identifier `json:"job_id"`

	Status JobState `json:"status"`
}

type Graph = dto.Graph

type Metrics = []dto.Metric

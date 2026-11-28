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

type WorkingStatus struct {
	TransportType    string           `json:"transport_type"`
	GraphAvailable   bool             `json:"graph_available"`
	MetricsAvailable bool             `json:"metrics_available"`
	Error            *AnalysisFailure `json:"error,omitempty"`
}

type AnalysisStatus struct {
	JobID           Identifier       `json:"job_id"`
	Status          JobState         `json:"status"`
	WorkingStatuses []WorkingStatus  `json:"working_statuses,omitempty"`
	Error           *AnalysisFailure `json:"error,omitempty"`
}

type JobStatus = AnalysisStatus

type AnalysisResult struct {
	Graph *Graph `json:"graph"`

	JobID Identifier `json:"job_id"`

	Metrics Metrics `json:"metrics"`

	Status JobState `json:"status"`

	WorkingStatuses []WorkingStatus `json:"working_statuses,omitempty"`
	WorkResults     []WorkResult    `json:"work_results,omitempty"`
}

type WorkResult struct {
	TransportType string  `json:"transport_type"`
	Graph         *Graph  `json:"graph"`
	Metrics       Metrics `json:"metrics"`
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

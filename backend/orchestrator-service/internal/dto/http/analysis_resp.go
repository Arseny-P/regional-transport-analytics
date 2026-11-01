package httpdto

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

type Graph struct {
	Edges []struct {
		Attributes *map[string]interface{} `json:"attributes,omitempty"`

		Geometry *[]Position `json:"geometry,omitempty"`

		ID Identifier `json:"id"`

		Source string `json:"source"`

		Target string `json:"target"`
	} `json:"edges"`
	Nodes []struct {
		Attributes *map[string]interface{} `json:"attributes,omitempty"`

		ID Identifier `json:"id"`

		Position Position `json:"position"`
	} `json:"nodes"`
}

type Metrics = []struct {
	Name  string  `json:"name"`
	Value float32 `json:"value"`
}

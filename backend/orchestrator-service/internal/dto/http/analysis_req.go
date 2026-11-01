package httpdto

type Transports = []string

type MapPoint struct {
	Latitude  float32 `json:"latitude"`
	Longitude float32 `json:"longitude"`
}

type AnalysisArea struct {
	FirstPoint MapPoint `json:"first_point"`

	SecondPoint MapPoint `json:"second_point"`
}

type CancelAnalysisParams struct {
	JobID JobID `form:"job_id" json:"job_id"`
}

type SendAnalysisHeartbeatParams struct {
	JobID JobID `form:"job_id" json:"job_id"`
}

type GetAnalysisResultParams struct {
	JobID JobID `form:"job_id" json:"job_id"`
}

type CreateAnalysisRequest struct {
	Area AnalysisArea `json:"area"`

	RegionID Identifier `json:"region_id"`

	Transports Transports `json:"transports"`
}

type CreateAnalysisJSONRequestBody = CreateAnalysisRequest

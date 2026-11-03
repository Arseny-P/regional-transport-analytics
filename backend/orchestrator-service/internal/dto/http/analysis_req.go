package httpdto

import "orchestrator-service/internal/dto"

type Transports = []string

type MapPoint = dto.MapPoint

type AnalysisArea = dto.AnalysisArea

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

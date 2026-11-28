package httpcontroller

import (
	"encoding/json"
	"net/http"
	"net/url"
	"orchestrator-service/internal/domain"
	"orchestrator-service/internal/dto"
	httpdto "orchestrator-service/internal/dto/http"
	"sort"
	"time"

	"github.com/google/uuid"
)

func (hc *HTTPController) SendAnalysisHeartbeatHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		receivedAt := time.Now()
		jobIDString := r.URL.Query().Get("job_id")
		if jobIDString == "" {
			hc.writeError(w, errMissingJobID)
			return
		}
		jobID, err := uuid.Parse(jobIDString)
		if err != nil {
			hc.writeError(w, errInvalidJobID)
			return
		}
		heartbeatErr := hc.heartbeatWorker.UpdateHeartbeat(jobID, receivedAt, receivedAt.Add(10*time.Second))
		response, err := hc.heartbeatWorker.GetHeartbeatResponse(r.Context(), jobID)
		if r.Context().Err() != nil {
			return
		}
		if err != nil {
			status, _ := ReturnErrorRespWithCode(err)
			if status == http.StatusInternalServerError {
				hc.logger.ErrorContext(r.Context(), "analysis heartbeat failed", "job_id", jobID, "error", err)
			}
			hc.writeError(w, err)
			return
		}
		if response.Status == "" {
			hc.logger.ErrorContext(r.Context(), "empty analysis heartbeat status", "job_id", jobID)
			hc.writeError(w, domain.ErrInternalServer)
			return
		}
		body := httpdto.AnalysisStatus{
			JobID:           jobIDString,
			Status:          httpdto.JobState(response.Status),
			WorkingStatuses: analysisWorkingStatuses(response.WorkResults),
		}
		if heartbeatErr != nil {
			status, errorBody := ReturnErrorRespWithCode(heartbeatErr)
			if status != http.StatusOK {
				if status == http.StatusInternalServerError {
					hc.logger.ErrorContext(r.Context(), "update heartbeat failed", "job_id", jobID, "error", heartbeatErr)
				}
				hc.WriteResponse(w, status, errorBody)
				return
			}
			body.Error = &httpdto.AnalysisFailure{
				Code: errorBody.Code, Message: errorBody.Message,
			}
		}
		hc.WriteResponse(w, http.StatusOK, body)
	}
}

func (hc *HTTPController) CancelAnalysisHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		jobIDString := r.URL.Query().Get("job_id")
		if jobIDString == "" {
			hc.writeError(w, errMissingJobID)
			return
		}
		jobID, err := uuid.Parse(jobIDString)
		if err != nil {
			hc.writeError(w, errInvalidJobID)
			return
		}

		result, pending, err := hc.jobUsecase.CancelJob(r.Context(), jobID)
		if err != nil {
			status, _ := ReturnErrorRespWithCode(err)
			if status == http.StatusInternalServerError && r.Context().Err() == nil {
				hc.logger.ErrorContext(r.Context(), "analysis cancellation failed", "job_id", jobID, "error", err)
			}
			hc.writeError(w, err)
			return
		}
		switch result.Payload.Status {
		case "completed", "failed":
			hc.writeError(w, domain.ErrJobAlreadyFinished)
			return
		case "cancel_requested", "canceled":
		default:
			hc.logger.ErrorContext(r.Context(), "unexpected analysis cancellation status", "job_id", jobID, "status", result.Payload.Status)
			hc.writeError(w, domain.ErrInternalServer)
			return
		}

		body := httpdto.AnalysisStatus{
			JobID:           result.JobID.String(),
			Status:          httpdto.JobState(result.Payload.Status),
			WorkingStatuses: analysisWorkingStatuses(result.WorkResults),
		}
		status := http.StatusOK
		if pending {
			status = http.StatusAccepted
		}
		hc.WriteResponse(w, status, body)
	}
}

func (hc *HTTPController) CreateAnalysisHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		jobIDString := r.URL.Query().Get("job_id")

		if jobIDString == "" {
			hc.writeError(w, errMissingJobID)
			return
		}

		jobID, err := uuid.Parse(jobIDString)
		if err != nil {
			hc.writeError(w, errInvalidJobID)
			return
		}

		var req httpdto.CreateAnalysisJSONRequestBody

		if decodeErr := json.NewDecoder(r.Body).Decode(&req); decodeErr != nil {
			hc.writeError(w, errInvalidJSON)
			return
		}

		if validationErr := validateAnalysisRequest(req); validationErr != nil {
			hc.writeError(w, validationErr)
			return
		}

		sort.Strings(req.Transports)
		transports := make([]domain.Transport, 0, len(req.Transports))

		for _, transport := range req.Transports {
			transportType := domain.Transport(transport)
			if len(transports) > 0 && transports[len(transports)-1] == transportType {
				continue
			}

			transports = append(transports, transportType)
		}

		regionID, err := uuid.Parse(req.RegionID)
		if err != nil {
			hc.writeError(w, errInvalidRegionID)
			return
		}
		jobStatus, isCreated, err := hc.jobUsecase.CreateJob(r.Context(), jobID, regionID,
			req.Area.FirstPoint.Latitude, req.Area.FirstPoint.Longitude,
			req.Area.SecondPoint.Latitude, req.Area.SecondPoint.Longitude,
			transports,
		)

		if err != nil {
			status, _ := ReturnErrorRespWithCode(err)
			if status == http.StatusInternalServerError && r.Context().Err() == nil {
				hc.logger.ErrorContext(r.Context(), "analysis request failed",
					"job_id", jobID, "region_id", regionID, "error", err)
			}
			hc.writeError(w, err)
			return
		}
		if isCreated {
			_ = hc.heartbeatWorker.UpdateHeartbeat(jobID, time.Now(), time.Now().Add(10*time.Second))
		}

		resp := httpdto.AnalysisReceipt{
			JobID:  jobIDString,
			Status: httpdto.JobState(jobStatus),
		}

		if isCreated {
			hc.WriteResponse(w, http.StatusAccepted, resp)
			return
		}

		hc.WriteResponse(w, http.StatusOK, resp)
	}
}

func (hc *HTTPController) GetAnalysisResultHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()
		jobIDString := query.Get("job_id")
		if jobIDString == "" {
			hc.writeError(w, errMissingJobID)
			return
		}
		jobID, err := uuid.Parse(jobIDString)
		if err != nil {
			hc.writeError(w, errInvalidJobID)
			return
		}
		transports, invalidField := analysisResultTransports(query)
		if invalidField != "" {
			hc.WriteResponse(w, http.StatusBadRequest, httpdto.Error{
				Code: "invalid_boolean", Field: invalidField, Message: "Ожидается true или false",
			})
			return
		}
		result, err := hc.jobUsecase.GetAnalysisResult(r.Context(), jobID, transports)
		if err != nil {
			status, _ := ReturnErrorRespWithCode(err)
			if status == http.StatusInternalServerError && r.Context().Err() == nil {
				hc.logger.ErrorContext(r.Context(), "get analysis result failed", "job_id", jobID, "error", err)
			}
			hc.writeError(w, err)
			return
		}
		resp := httpdto.AnalysisResult{
			JobID:           result.JobID.String(),
			Status:          httpdto.JobState(result.Payload.Status),
			WorkingStatuses: analysisWorkingStatuses(result.WorkResults),
			Graph:           analysisGraph(result.Payload.Graph),
			Metrics:         analysisMetrics(result.Payload.Metrics),
		}
		if len(result.WorkResults) > 1 {
			resp.WorkResults = make([]httpdto.WorkResult, 0, len(result.WorkResults))
			for _, work := range result.WorkResults {
				resp.WorkResults = append(resp.WorkResults, httpdto.WorkResult{
					TransportType: string(work.TransportType),
					Graph:         analysisGraph(work.Payload.Graph),
					Metrics:       analysisMetrics(work.Payload.Metrics),
				})
			}
		}
		hc.WriteResponse(w, http.StatusOK, resp)
	}
}

func analysisResultTransports(query url.Values) (transports []domain.Transport, invalidField string) {
	options := [...]struct {
		field     string
		transport domain.Transport
	}{
		{field: "is_road", transport: domain.Road},
		{field: "is_rail", transport: domain.Rail},
	}
	transports = make([]domain.Transport, 0, len(options))
	for _, option := range options {
		if !query.Has(option.field) {
			continue
		}
		switch query.Get(option.field) {
		case "true":
			transports = append(transports, option.transport)
		case "false":
		default:
			return nil, option.field
		}
	}
	return transports, ""
}

func analysisWorkingStatuses(works []*domain.WorksRes) []httpdto.WorkingStatus {
	statuses := make([]httpdto.WorkingStatus, 0, len(works))
	for _, work := range works {
		status := httpdto.WorkingStatus{
			TransportType:    string(work.TransportType),
			GraphAvailable:   work.GraphAvailable,
			MetricsAvailable: work.MetricsAvailable,
		}
		if err := work.Payload.Error; err != nil {
			status.Error = &httpdto.AnalysisFailure{Code: err.Code, Message: err.Message}
		}
		statuses = append(statuses, status)
	}
	return statuses
}

func analysisGraph(graph *domain.Graph) *httpdto.Graph {
	if graph == nil {
		return nil
	}
	result := &httpdto.Graph{
		Nodes: make([]dto.GraphNode, 0, len(graph.Nodes)),
		Edges: make([]dto.GraphEdge, 0, len(graph.Edges)),
	}
	for _, node := range graph.Nodes {
		result.Nodes = append(result.Nodes, dto.GraphNode{
			ID: node.ID, Position: node.Position, Attributes: node.Attributes,
		})
	}
	for _, edge := range graph.Edges {
		result.Edges = append(result.Edges, dto.GraphEdge{
			ID: edge.ID, Source: edge.Source, Target: edge.Target,
			SegmentID: edge.SegmentID, Geometry: edge.Geometry, Attributes: edge.Attributes,
		})
	}
	return result
}

func analysisMetrics(metrics []domain.Metric) httpdto.Metrics {
	result := make(httpdto.Metrics, 0, len(metrics))
	for _, metric := range metrics {
		result = append(result, dto.Metric{NodeID: metric.NodeID, Name: metric.Name, Value: metric.Value})
	}
	return result
}

func validateAnalysisRequest(req httpdto.CreateAnalysisRequest) error {
	for _, point := range []httpdto.MapPoint{req.Area.FirstPoint, req.Area.SecondPoint} {
		if !(point.Latitude >= -90 && point.Latitude <= 90 &&
			point.Longitude >= -180 && point.Longitude <= 180) {
			return domain.ErrInvalidCoordinates
		}
	}
	if req.Area.FirstPoint.Latitude == req.Area.SecondPoint.Latitude ||
		req.Area.FirstPoint.Longitude == req.Area.SecondPoint.Longitude {
		return domain.ErrInvalidArea
	}
	if len(req.Transports) == 0 {
		return domain.ErrInvalidTransports
	}
	for _, transport := range req.Transports {
		switch domain.Transport(transport) {
		case domain.Road, domain.Rail, domain.Sea:
		default:
			return domain.ErrInvalidTransports
		}
	}
	return nil
}

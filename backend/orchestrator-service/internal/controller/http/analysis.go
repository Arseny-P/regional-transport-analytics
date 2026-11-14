package httpcontroller

import (
	"encoding/json"
	"net/http"
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
			JobID:            jobIDString,
			Status:           httpdto.JobState(response.Status),
			GraphAvailable:   response.GraphAvailable,
			MetricsAvailable: response.MetricsAvailable,
		}
		if response.Error != nil {
			body.Error = &httpdto.AnalysisFailure{
				Code: response.Error.Code, Message: response.Error.Message,
			}
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
			JobID:            result.JobID.String(),
			Status:           httpdto.JobState(result.Payload.Status),
			GraphAvailable:   result.GraphAvailable,
			MetricsAvailable: result.MetricsAvailable,
		}
		if result.Payload.Error != nil {
			body.Error = &httpdto.AnalysisFailure{
				Code: result.Payload.Error.Code, Message: result.Payload.Error.Message,
			}
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
		result, err := hc.jobUsecase.GetAnalysisResult(r.Context(), jobID)
		if err != nil {
			status, _ := ReturnErrorRespWithCode(err)
			if status == http.StatusInternalServerError && r.Context().Err() == nil {
				hc.logger.ErrorContext(r.Context(), "get analysis result failed", "job_id", jobID, "error", err)
			}
			hc.writeError(w, err)
			return
		}
		resp := httpdto.AnalysisResult{
			JobID:            result.JobID.String(),
			Status:           httpdto.JobState(result.Payload.Status),
			GraphAvailable:   result.GraphAvailable,
			MetricsAvailable: result.MetricsAvailable,
			Metrics:          make(httpdto.Metrics, 0, len(result.Payload.Metrics)),
		}
		if result.Payload.Error != nil {
			resp.Error = &httpdto.AnalysisFailure{
				Code: result.Payload.Error.Code, Message: result.Payload.Error.Message,
			}
		}
		if graph := result.Payload.Graph; graph != nil {
			resp.Graph = &httpdto.Graph{
				Nodes: make([]dto.GraphNode, 0, len(graph.Nodes)),
				Edges: make([]dto.GraphEdge, 0, len(graph.Edges)),
			}
			for _, node := range graph.Nodes {
				resp.Graph.Nodes = append(resp.Graph.Nodes, dto.GraphNode{
					ID: node.ID, Position: node.Position, Attributes: node.Attributes,
				})
			}
			for _, edge := range graph.Edges {
				resp.Graph.Edges = append(resp.Graph.Edges, dto.GraphEdge{
					ID: edge.ID, Source: edge.Source, Target: edge.Target,
					SegmentID: edge.SegmentID,
					Geometry:  edge.Geometry, Attributes: edge.Attributes,
				})
			}
		}
		var dtoMetric dto.Metric
		for _, metric := range result.Payload.Metrics {
			dtoMetric = dto.Metric{Name: metric.Name, Value: metric.Value}
			if metric.NodeID != nil {
				dtoMetric.NodeID = metric.NodeID
			}
			resp.Metrics = append(resp.Metrics, dtoMetric)
		}
		hc.WriteResponse(w, http.StatusOK, resp)
	}
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

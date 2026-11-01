package httpcontroller

import (
	"encoding/json"
	"net/http"
	"orchestrator-service/internal/domain"
	httpdto "orchestrator-service/internal/dto/http"
	"sort"

	"github.com/google/uuid"
)

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
		jobStatus, isCreated, err := hc.usecaseOrchestrator.CreateJob(r.Context(), jobID, regionID,
			req.Area.FirstPoint.Latitude, req.Area.FirstPoint.Longitude,
			req.Area.SecondPoint.Latitude, req.Area.SecondPoint.Longitude,
			transports,
		)

		if err != nil {
			status, _ := ReturnErrorRespWithCode(err)
			if status >= http.StatusInternalServerError && r.Context().Err() == nil {
				hc.logger.ErrorContext(r.Context(), "analysis request failed",
					"job_id", jobID, "region_id", regionID, "error", err)
			}
			hc.writeError(w, err)
			return
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

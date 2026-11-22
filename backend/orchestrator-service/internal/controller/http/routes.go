package httpcontroller

import "net/http"

func (hc *HTTPController) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("POST /analysis", hc.CreateAnalysisHandler())
	mux.HandleFunc("POST /analysis/heartbeat", hc.SendAnalysisHeartbeatHandler())
	mux.HandleFunc("POST /analysis/cancel", hc.CancelAnalysisHandler())
	mux.HandleFunc("POST /regions", hc.AddRegionHandler())
	mux.HandleFunc("GET /regions", hc.GetRegionsHandler())
	mux.HandleFunc("GET /regions/{region_id}", hc.GetRegionHandler())
	mux.HandleFunc("GET /analysis/result", hc.GetAnalysisResultHandler())
	return hc.LoggingMiddleware(hc.RecoverMiddleware(mux))
}

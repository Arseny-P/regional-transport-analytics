package httpcontroller

import "net/http"

func (hc *HTTPController) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("POST /analysis", hc.CreateAnalysisHandler())
	return hc.LoggingMiddleware(hc.RecoverMiddleware(mux))
}

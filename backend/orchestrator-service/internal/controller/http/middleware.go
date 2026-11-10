package httpcontroller

import (
	"net/http"
	"orchestrator-service/internal/domain"
	"runtime/debug"
	"time"
)

func (hc *HTTPController) LoggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			next.ServeHTTP(w, r)
			return
		}
		started := time.Now()
		defer func() {
			hc.logger.InfoContext(r.Context(), "HTTP request",
				"method", r.Method,
				"path", r.URL.Path,
				"duration", time.Since(started),
			)
		}()
		next.ServeHTTP(w, r)
	})
}

func (hc *HTTPController) RecoverMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				hc.logger.ErrorContext(r.Context(), "HTTP panic",
					"method", r.Method,
					"path", r.URL.Path,
					"panic", recovered,
					"stack", string(debug.Stack()),
				)
				hc.writeError(w, domain.ErrInternalServer)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

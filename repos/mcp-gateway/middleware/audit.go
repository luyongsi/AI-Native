package middleware

import (
	"log"
	"net/http"
	"time"
)

// Audit is an HTTP middleware that logs request details to stdout/stderr.
func Audit(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()

		// Wrap the response writer to capture the status code.
		arw := &auditResponseWriter{ResponseWriter: w, statusCode: http.StatusOK}

		next(arw, r)

		duration := time.Since(start)

		agentID := r.Header.Get("X-Agent-ID")
		reqID := r.Header.Get("X-Req-ID")
		if agentID == "" {
			agentID = "anonymous"
		}
		if reqID == "" {
			reqID = "-"
		}

		log.Printf("[AUDIT] agent=%s req_id=%s method=%s path=%s status=%d duration=%s remote=%s",
			agentID,
			reqID,
			r.Method,
			r.URL.Path,
			arw.statusCode,
			duration,
			r.RemoteAddr,
		)

		if arw.statusCode >= 500 {
			log.Printf("[AUDIT ERROR] agent=%s req_id=%s method=%s path=%s status=%d duration=%s",
				agentID, reqID, r.Method, r.URL.Path, arw.statusCode, duration)
		}
	}
}

type auditResponseWriter struct {
	http.ResponseWriter
	statusCode int
}

func (arw *auditResponseWriter) WriteHeader(code int) {
	arw.statusCode = code
	arw.ResponseWriter.WriteHeader(code)
}

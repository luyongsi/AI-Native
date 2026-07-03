package auth

import (
	"log"
	"net/http"
	"os"
	"strings"
)

// MCPJWTMiddleware returns an HTTP middleware that validates RS256 JWT tokens
// against the MCP Gateway public key. In dev mode (default for stub), all
// requests pass through.
func MCPJWTMiddleware(publicKey string) func(http.Handler) http.Handler {
	devMode := os.Getenv("VISAGENT_DEV_MODE")
	if devMode == "" {
		devMode = "true"
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Stub: always pass in dev mode
			if strings.EqualFold(devMode, "true") {
				log.Printf("[auth] DEV MODE: skipping JWT validation for %s %s", r.Method, r.URL.Path)
				next.ServeHTTP(w, r)
				return
			}

			authHeader := r.Header.Get("Authorization")
			if authHeader == "" {
				writeAuthError(w, "missing Authorization header")
				return
			}

			parts := strings.SplitN(authHeader, " ", 2)
			if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
				writeAuthError(w, "invalid Authorization header format")
				return
			}

			tokenStr := parts[1]

			// Stub: validate token structure without actual crypto
			if tokenStr == "" || len(tokenStr) < 10 {
				writeAuthError(w, "invalid token format")
				return
			}

			// In production this would validate the RS256 signature against publicKey.
			// Stub simply passes through with a log.
			log.Printf("[auth] JWT token accepted (stub validation) for %s %s", r.Method, r.URL.Path)
			next.ServeHTTP(w, r)
		})
	}
}

func writeAuthError(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	w.Write([]byte(`{"error":"` + msg + `"}`))
}

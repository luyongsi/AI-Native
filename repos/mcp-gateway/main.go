package main

import (
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"mcp-gateway/auth"
	"mcp-gateway/middleware"
	"mcp-gateway/server"
)

func main() {
	registry := server.NewToolRegistry()

	mcBackendURL := os.Getenv("MC_BACKEND_URL")
	if mcBackendURL == "" {
		mcBackendURL = "http://localhost:8000"
	}
	router := server.NewToolRouter(registry, mcBackendURL)
	mcp := server.NewMCPServer(registry, router)

	jwtAuth := auth.NewJWTAuth()
	mux := http.NewServeMux()

	mux.HandleFunc("/tools/list", middleware.Chain(
		mcp.HandleListTools,
		jwtAuth.Verify,
		middleware.RateLimit,
		middleware.Audit,
	))

	mux.HandleFunc("/tools/call", middleware.Chain(
		mcp.HandleCallTool,
		jwtAuth.Verify,
		middleware.RateLimit,
		middleware.Audit,
	))

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	mux.HandleFunc("/auth/token", jwtAuth.HandleIssueToken)

	log.Println("MCP Gateway starting on :8081")

	go func() {
		if err := http.ListenAndServe(":8081", mux); err != nil {
			log.Fatalf("Server failed: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Println("MCP Gateway shutting down")
}

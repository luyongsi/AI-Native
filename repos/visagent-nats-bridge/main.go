package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/nats-io/nats.go"
)

// Config holds the runtime configuration for the NATS bridge.
type Config struct {
	NatsURL       string
	VisAgentURL   string
	HealthPort    string
	ReconnectWait time.Duration
	MaxReconnects int
}

func loadConfig() Config {
	cfg := Config{
		NatsURL:       getEnv("NATS_URL", "nats://localhost:4222"),
		VisAgentURL:   getEnv("VISAGENT_URL", "http://localhost:8080"),
		HealthPort:    getEnv("HEALTH_PORT", "8080"),
		ReconnectWait: 2 * time.Second,
		MaxReconnects: 10,
	}
	return cfg
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// NATSEvent represents a generic NATS message payload.
type NATSEvent struct {
	EventType string          `json:"event_type"`
	Timestamp string          `json:"timestamp"`
	Payload   json.RawMessage `json:"payload"`
}

func main() {
	cfg := loadConfig()

	log.Println("=== VisAgent NATS Bridge Starting ===")
	log.Printf("Configuration:")
	log.Printf("  NATS_URL:        %s", cfg.NatsURL)
	log.Printf("  VISAGENT_URL:    %s", cfg.VisAgentURL)
	log.Printf("  HEALTH_PORT:     %s", cfg.HealthPort)
	log.Printf("  ReconnectWait:   %v", cfg.ReconnectWait)
	log.Printf("  MaxReconnects:   %d", cfg.MaxReconnects)

	// Connect to NATS
	nc, err := nats.Connect(cfg.NatsURL,
		nats.ReconnectWait(cfg.ReconnectWait),
		nats.MaxReconnects(cfg.MaxReconnects),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			log.Printf("[NATS] Disconnected: %v", err)
		}),
		nats.ReconnectHandler(func(_ *nats.Conn) {
			log.Println("[NATS] Reconnected")
		}),
		nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) {
			log.Printf("[NATS] Error: %v", err)
		}),
	)
	if err != nil {
		log.Fatalf("Failed to connect to NATS: %v", err)
	}
	defer nc.Close()

	log.Printf("[NATS] Connected to %s", cfg.NatsURL)

	// Subscribe to test.completed events
	subTestCompleted, err := nc.Subscribe("test.completed", func(msg *nats.Msg) {
		handleEvent("test.completed", msg.Data)
	})
	if err != nil {
		log.Fatalf("Failed to subscribe to test.completed: %v", err)
	}
	defer subTestCompleted.Unsubscribe()
	log.Println("[NATS] Subscribed to: test.completed")

	// Subscribe to agent.status.changed events
	subAgentStatus, err := nc.Subscribe("agent.status.changed", func(msg *nats.Msg) {
		handleEvent("agent.status.changed", msg.Data)
	})
	if err != nil {
		log.Fatalf("Failed to subscribe to agent.status.changed: %v", err)
	}
	defer subAgentStatus.Unsubscribe()
	log.Println("[NATS] Subscribed to: agent.status.changed")

	// Subscribe to loop.tripped events
	subLoopTripped, err := nc.Subscribe("loop.tripped", func(msg *nats.Msg) {
		handleEvent("loop.tripped", msg.Data)
	})
	if err != nil {
		log.Fatalf("Failed to subscribe to loop.tripped: %v", err)
	}
	defer subLoopTripped.Unsubscribe()
	log.Println("[NATS] Subscribed to: loop.tripped")

	// Health check HTTP server
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		if nc.IsConnected() {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte(`{"status":"healthy","nats":"connected"}`))
		} else {
			w.WriteHeader(http.StatusServiceUnavailable)
			w.Write([]byte(`{"status":"unhealthy","nats":"disconnected"}`))
		}
	})

	healthAddr := fmt.Sprintf(":%s", cfg.HealthPort)
	go func() {
		log.Printf("[HTTP] Health check server listening on %s", healthAddr)
		if err := http.ListenAndServe(healthAddr, nil); err != nil {
			log.Printf("[HTTP] Health server error: %v", err)
		}
	}()

	log.Println("VisAgent NATS Bridge is running. Press Ctrl+C to exit.")

	// Wait for shutdown signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Println("VisAgent NATS Bridge shutting down...")
}

func handleEvent(subject string, data []byte) {
	var event NATSEvent
	if err := json.Unmarshal(data, &event); err != nil {
		// If it doesn't match the generic format, log raw
		log.Printf("[NATS] <%s> raw: %s", subject, string(data))
		return
	}

	log.Printf("[NATS] <%s> event_type=%s timestamp=%s", subject, event.EventType, event.Timestamp)

	// Stub: in production this would forward to VisAgent API
	// visagentURL + "/events" with the event payload
}

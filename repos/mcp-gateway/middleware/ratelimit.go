package middleware

import (
	"encoding/json"
	"net/http"
	"sync"
	"time"
)

// RateLimiter implements per-agent rate limiting using a sliding window.
type RateLimiter struct {
	mu       sync.Mutex
	agents   map[string]*agentWindow
	maxReqs  int
	interval time.Duration
}

type agentWindow struct {
	requests []time.Time
}

// NewRateLimiter creates a new rate limiter with the given configuration.
func NewRateLimiter(maxReqs int, interval time.Duration) *RateLimiter {
	rl := &RateLimiter{
		agents:   make(map[string]*agentWindow),
		maxReqs:  maxReqs,
		interval: interval,
	}
	// Periodically clean up stale agent entries.
	go rl.cleanup()
	return rl
}

// DefaultRateLimiter returns a rate limiter with 100 requests per minute.
func DefaultRateLimiter() *RateLimiter {
	return NewRateLimiter(100, 1*time.Minute)
}

// Allow checks if the given agent is within the rate limit.
func (rl *RateLimiter) Allow(agentID string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	aw, ok := rl.agents[agentID]
	if !ok {
		aw = &agentWindow{}
		rl.agents[agentID] = aw
	}

	now := time.Now()
	cutoff := now.Add(-rl.interval)

	// Evict expired timestamps.
	valid := aw.requests[:0]
	for _, t := range aw.requests {
		if t.After(cutoff) {
			valid = append(valid, t)
		}
	}
	aw.requests = valid

	if len(aw.requests) >= rl.maxReqs {
		return false
	}

	aw.requests = append(aw.requests, now)
	return true
}

func (rl *RateLimiter) cleanup() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		rl.mu.Lock()
		cutoff := time.Now().Add(-rl.interval * 2)
		for id, aw := range rl.agents {
			valid := aw.requests[:0]
			for _, t := range aw.requests {
				if t.After(cutoff) {
					valid = append(valid, t)
				}
			}
			if len(valid) == 0 {
				delete(rl.agents, id)
			} else {
				aw.requests = valid
			}
		}
		rl.mu.Unlock()
	}
}

var defaultLimiter = DefaultRateLimiter()

// RateLimit is an HTTP middleware that enforces per-agent rate limiting.
// The agent ID is read from the X-Agent-ID header (set by JWT verification).
func RateLimit(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		agentID := r.Header.Get("X-Agent-ID")
		if agentID == "" {
			// Allow unauthenticated requests through (JWT middleware handles auth).
			next(w, r)
			return
		}

		if !defaultLimiter.Allow(agentID) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Retry-After", "60")
			w.WriteHeader(http.StatusTooManyRequests)
			json.NewEncoder(w).Encode(map[string]string{
				"error":    "rate limit exceeded",
				"agent_id": agentID,
				"limit":    "100 requests per minute",
			})
			return
		}

		next(w, r)
	}
}

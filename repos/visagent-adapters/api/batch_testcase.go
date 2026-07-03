package api

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"
)

// BatchCreateRequest represents a request to create multiple test cases at once.
type BatchCreateRequest struct {
	ExternalID         string   `json:"external_id"`
	Title              string   `json:"title"`
	Steps              []string `json:"steps"`
	Preconditions      string   `json:"preconditions"`
	Priority           string   `json:"priority"`
	Tags               []string `json:"tags"`
	AutoGenerateScript bool     `json:"auto_generate_script"`
}

// BatchCreateResponse is returned after batch test case creation.
type BatchCreateResponse struct {
	CreatedIDs []string `json:"created_ids"`
	Count      int      `json:"count"`
	Status     string   `json:"status"`
}

// BatchCreateTestCasesHandler handles POST requests to create multiple test cases.
func BatchCreateTestCasesHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONError(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var requests []BatchCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&requests); err != nil {
		writeJSONError(w, fmt.Sprintf("invalid request body: %v", err), http.StatusBadRequest)
		return
	}

	if len(requests) == 0 {
		writeJSONError(w, "at least one test case is required", http.StatusBadRequest)
		return
	}

	if len(requests) > 100 {
		writeJSONError(w, "batch size cannot exceed 100", http.StatusBadRequest)
		return
	}

	// Validate each request
	for i, req := range requests {
		if req.Title == "" {
			writeJSONError(w, fmt.Sprintf("test case at index %d is missing title", i), http.StatusBadRequest)
			return
		}
		if req.Priority == "" {
			requests[i].Priority = "medium"
		}
	}

	// Generate mock test case IDs
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	createdIDs := make([]string, 0, len(requests))
	for range requests {
		id := fmt.Sprintf("TC-%d-%04d", time.Now().Unix(), rng.Intn(10000))
		createdIDs = append(createdIDs, id)
	}

	log.Printf("[api] Batch created %d test cases", len(createdIDs))

	resp := BatchCreateResponse{
		CreatedIDs: createdIDs,
		Count:      len(createdIDs),
		Status:     "created",
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(resp)
}

func writeJSONError(w http.ResponseWriter, msg string, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

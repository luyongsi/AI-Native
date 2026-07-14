package backend

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// KnowledgeClient wraps HTTP calls to the MC Backend knowledge API.
type KnowledgeClient struct {
	baseURL    string
	httpClient *http.Client
}

// NewKnowledgeClient creates a client targeting the MC Backend.
func NewKnowledgeClient(baseURL string) *KnowledgeClient {
	return &KnowledgeClient{
		baseURL:    strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
}

// SearchSimilarRequirements calls POST /api/knowledge/search with content_type=requirement.
func (kc *KnowledgeClient) SearchSimilarRequirements(args map[string]interface{}) (interface{}, error) {
	query, _ := args["query"].(string)
	limit := 5
	if v, ok := args["limit"].(float64); ok {
		limit = int(v)
	}
	return kc.doSearch(query, "requirement", limit)
}

// SearchKnownIssues calls POST /api/knowledge/search with content_type=issue.
func (kc *KnowledgeClient) SearchKnownIssues(args map[string]interface{}) (interface{}, error) {
	query, _ := args["query"].(string)
	limit := 10
	if v, ok := args["limit"].(float64); ok {
		limit = int(v)
	}
	return kc.doSearch(query, "issue", limit)
}

// GetDomainRisks calls POST /api/knowledge/search with content_type=doc,
// using a domain-prefixed query.
func (kc *KnowledgeClient) GetDomainRisks(args map[string]interface{}) (interface{}, error) {
	domain, _ := args["domain"].(string)
	if domain == "" {
		domain = "general"
	}
	query := fmt.Sprintf("domain:%s risks", domain)
	return kc.doSearch(query, "doc", 10)
}

func (kc *KnowledgeClient) doSearch(query, contentType string, limit int) (interface{}, error) {
	u, err := url.Parse(kc.baseURL + "/api/knowledge/search")
	if err != nil {
		return nil, fmt.Errorf("invalid base URL: %w", err)
	}
	q := u.Query()
	q.Set("query", query)
	if contentType != "" {
		q.Set("content_type", contentType)
	}
	q.Set("limit", fmt.Sprintf("%d", limit))
	u.RawQuery = q.Encode()

	reqBody := map[string]interface{}{}
	bodyBytes, _ := json.Marshal(reqBody)

	req, err := http.NewRequest("POST", u.String(), bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := kc.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("knowledge backend unreachable: %w", err)
	}
	defer resp.Body.Close()

	respBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("knowledge backend returned %d: %s", resp.StatusCode, string(respBytes))
	}

	var result interface{}
	if err := json.Unmarshal(respBytes, &result); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}
	return result, nil
}

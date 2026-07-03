package llm

import (
	"encoding/base64"
	"fmt"
	"math/rand"
	"time"
)

// AnalysisResult represents the outcome of a visual analysis.
type AnalysisResult struct {
	Passed      bool     `json:"passed"`
	Issues      []string `json:"issues"`
	Confidence  float64  `json:"confidence"`
	RawResponse string   `json:"raw_response"`
}

// QwenAdapter provides an interface to the Qwen VL (Vision-Language) model
// for VisAgent visual testing.
type QwenAdapter struct {
	apiKey  string
	baseURL string
	model   string
}

// NewQwenAdapter creates a new QwenAdapter with the given credentials.
func NewQwenAdapter(apiKey, baseURL, model string) *QwenAdapter {
	if model == "" {
		model = "qwen-vl-max"
	}
	return &QwenAdapter{
		apiKey:  apiKey,
		baseURL: baseURL,
		model:   model,
	}
}

// AnalyzeScreenshot sends an image and prompt to the Qwen VL model and returns
// an analysis result. This is a stub implementation that returns a mock result.
func (q *QwenAdapter) AnalyzeScreenshot(imageBase64 string, prompt string) (*AnalysisResult, error) {
	if imageBase64 == "" {
		return nil, fmt.Errorf("imageBase64 must not be empty")
	}
	if prompt == "" {
		return nil, fmt.Errorf("prompt must not be empty")
	}

	// Decode to validate base64 input is well-formed
	_, err := base64.StdEncoding.DecodeString(imageBase64)
	if err != nil {
		return nil, fmt.Errorf("invalid base64 image data: %w", err)
	}

	// Simulate network latency
	time.Sleep(50 * time.Millisecond)

	// Deterministic-enough mock: seed with current second for variety
	rng := rand.New(rand.NewSource(time.Now().Unix()))
	passed := rng.Float64() > 0.15 // 85% pass rate in mock

	var issues []string
	if !passed {
		issues = []string{
			"Button alignment off by 2px in header",
			"Color contrast ratio below WCAG AA threshold on primary CTA",
		}
	}

	return &AnalysisResult{
		Passed:     passed,
		Issues:     issues,
		Confidence: 0.85 + rng.Float64()*0.14,
		RawResponse: fmt.Sprintf(
			`{"model":"%s","choices":[{"message":{"content":"Mock Qwen VL analysis"}}]}`,
			q.model,
		),
	}, nil
}

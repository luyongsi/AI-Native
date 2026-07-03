package server

import (
	"fmt"
	"net/http"
	"time"
)

// ToolRouter routes tool calls to backend services.
type ToolRouter struct {
	registry *ToolRegistry
	client   *http.Client
}

// NewToolRouter creates a new ToolRouter.
func NewToolRouter(registry *ToolRegistry) *ToolRouter {
	return &ToolRouter{
		registry: registry,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// Route dispatches a tool call by name to the appropriate backend.
// In development mode, it returns mock responses for all tools.
func (tr *ToolRouter) Route(name string, args map[string]interface{}) (interface{}, error) {
	if _, ok := tr.registry.GetTool(name); !ok {
		return nil, fmt.Errorf("unknown tool: %s", name)
	}

	// Mock response for all tools during development.
	return tr.mockResponse(name, args), nil
}

func (tr *ToolRouter) mockResponse(name string, args map[string]interface{}) map[string]interface{} {
	result := map[string]interface{}{
		"status":              "success",
		"tool":                name,
		"message":             fmt.Sprintf("Mock response from %s -- backend not yet connected", name),
		"input_args_received": len(args),
		"timestamp":           time.Now().UTC().Format(time.RFC3339),
	}

	argKeys := make([]string, 0, len(args))
	for k := range args {
		argKeys = append(argKeys, k)
	}
	result["arg_keys"] = argKeys

	return result
}

package server

import (
	"fmt"
	"net/http"
	"time"

	"mcp-gateway/backend"
)

// ToolRouter routes tool calls to backend services.
type ToolRouter struct {
	registry  *ToolRegistry
	client    *http.Client
	knowledge *backend.KnowledgeClient
}

var knowledgeToolNames = map[string]bool{
	"search_similar_requirements": true,
	"search_known_issues":         true,
	"get_domain_risks":            true,
}

// NewToolRouter creates a new ToolRouter.
// knowledgeBackendURL is the base URL of the MC Backend (e.g. http://localhost:8000).
func NewToolRouter(registry *ToolRegistry, knowledgeBackendURL string) *ToolRouter {
	return &ToolRouter{
		registry:  registry,
		client:    &http.Client{Timeout: 30 * time.Second},
		knowledge: backend.NewKnowledgeClient(knowledgeBackendURL),
	}
}

// Route dispatches a tool call by name to the appropriate backend.
// Knowledge tools are routed to the real MC Backend; all others return mock responses.
func (tr *ToolRouter) Route(name string, args map[string]interface{}) (interface{}, error) {
	if _, ok := tr.registry.GetTool(name); !ok {
		return nil, fmt.Errorf("unknown tool: %s", name)
	}

	if knowledgeToolNames[name] {
		return tr.routeKnowledgeBackend(name, args)
	}
	return tr.mockResponse(name, args), nil
}

func (tr *ToolRouter) routeKnowledgeBackend(name string, args map[string]interface{}) (interface{}, error) {
	switch name {
	case "search_similar_requirements":
		return tr.knowledge.SearchSimilarRequirements(args)
	case "search_known_issues":
		return tr.knowledge.SearchKnownIssues(args)
	case "get_domain_risks":
		return tr.knowledge.GetDomainRisks(args)
	default:
		return nil, fmt.Errorf("unknown knowledge tool: %s", name)
	}
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

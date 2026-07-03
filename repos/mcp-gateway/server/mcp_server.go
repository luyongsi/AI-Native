package server

import (
	"encoding/json"
	"net/http"
)

// MCPServer handles MCP protocol requests.
type MCPServer struct {
	registry *ToolRegistry
	router   *ToolRouter
}

// NewMCPServer creates a new MCPServer.
func NewMCPServer(registry *ToolRegistry, router *ToolRouter) *MCPServer {
	return &MCPServer{
		registry: registry,
		router:   router,
	}
}

// ToolListResponse mirrors the MCP tools/list response.
type ToolListResponse struct {
	JSONRPC string `json:"jsonrpc"`
	ID      int    `json:"id"`
	Result  struct {
		Tools []ToolDef `json:"tools"`
	} `json:"result"`
}

// ToolDef represents a single tool definition.
type ToolDef struct {
	Name        string      `json:"name"`
	Description string      `json:"description"`
	InputSchema InputSchema `json:"inputSchema"`
}

// InputSchema is the JSON Schema for tool inputs.
type InputSchema struct {
	Type       string             `json:"type"`
	Properties map[string]PropDef `json:"properties"`
	Required   []string           `json:"required,omitempty"`
}

// PropDef describes a property in the input schema.
type PropDef struct {
	Type        string `json:"type"`
	Description string `json:"description"`
}

// CallToolRequest is the MCP tools/call request body.
type CallToolRequest struct {
	JSONRPC string `json:"jsonrpc"`
	ID      int    `json:"id"`
	Method  string `json:"method"`
	Params  struct {
		Name      string                 `json:"name"`
		Arguments map[string]interface{} `json:"arguments"`
	} `json:"params"`
}

// CallToolResponse is the MCP tools/call response body.
type CallToolResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      int         `json:"id"`
	Result  interface{} `json:"result"`
	Error   *MCPError   `json:"error,omitempty"`
}

// MCPError represents an MCP protocol error.
type MCPError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// HandleListTools handles GET /tools/list — returns all registered tool definitions.
func (s *MCPServer) HandleListTools(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, CallToolResponse{Error: &MCPError{Code: -32601, Message: "method not allowed"}})
		return
	}

	tools := s.registry.ListTools()
	resp := ToolListResponse{
		JSONRPC: "2.0",
		ID:      1,
	}
	resp.Result.Tools = tools
	writeJSON(w, http.StatusOK, resp)
}

// HandleCallTool handles POST /tools/call — routes to the appropriate backend.
func (s *MCPServer) HandleCallTool(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, CallToolResponse{Error: &MCPError{Code: -32601, Message: "method not allowed"}})
		return
	}

	var req CallToolRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, CallToolResponse{Error: &MCPError{Code: -32700, Message: "parse error: " + err.Error()}})
		return
	}

	result, err := s.router.Route(req.Params.Name, req.Params.Arguments)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, CallToolResponse{
			JSONRPC: req.JSONRPC,
			ID:      req.ID,
			Error:   &MCPError{Code: -32000, Message: err.Error()},
		})
		return
	}

	resp := CallToolResponse{
		JSONRPC: req.JSONRPC,
		ID:      req.ID,
		Result:  result,
	}
	writeJSON(w, http.StatusOK, resp)
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

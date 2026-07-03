package server

import "sync"

// ToolRegistry holds metadata for all 31 skills as MCP tool definitions.
type ToolRegistry struct {
	mu     sync.RWMutex
	tools  []ToolDef
	byName map[string]ToolDef
}

// NewToolRegistry creates a registry pre-populated with all 31 skills.
func NewToolRegistry() *ToolRegistry {
	tr := &ToolRegistry{
		byName: make(map[string]ToolDef),
	}
	tr.registerAll()
	return tr
}

// ListTools returns all registered tools.
func (tr *ToolRegistry) ListTools() []ToolDef {
	tr.mu.RLock()
	defer tr.mu.RUnlock()
	out := make([]ToolDef, len(tr.tools))
	copy(out, tr.tools)
	return out
}

// GetTool returns a tool by name.
func (tr *ToolRegistry) GetTool(name string) (ToolDef, bool) {
	tr.mu.RLock()
	defer tr.mu.RUnlock()
	t, ok := tr.byName[name]
	return t, ok
}

// registerAll populates the 31 skills from doc 04 Section 7.
func (tr *ToolRegistry) registerAll() {
	tools := []ToolDef{
		// 1. code_review
		{
			Name:        "code_review",
			Description: "Review code for quality, bugs, and best practices",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":     {Type: "string", Description: "Code to review"},
					"language": {Type: "string", Description: "Programming language of the code"},
					"context":  {Type: "string", Description: "Additional context for the review"},
				},
				Required: []string{"code"},
			},
		},

		// 2. code_generation
		{
			Name:        "code_generation",
			Description: "Generate code based on a specification or prompt",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"prompt":       {Type: "string", Description: "Description of the code to generate"},
					"language":     {Type: "string", Description: "Target programming language"},
					"requirements": {Type: "string", Description: "Detailed requirements or constraints"},
				},
				Required: []string{"prompt"},
			},
		},

		// 3. code_explanation
		{
			Name:        "code_explanation",
			Description: "Explain how a piece of code works",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":     {Type: "string", Description: "Code to explain"},
					"language": {Type: "string", Description: "Programming language"},
					"level":    {Type: "string", Description: "Detail level: beginner, intermediate, expert"},
				},
				Required: []string{"code"},
			},
		},

		// 4. code_refactoring
		{
			Name:        "code_refactoring",
			Description: "Refactor code for better structure and readability",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":        {Type: "string", Description: "Code to refactor"},
					"language":    {Type: "string", Description: "Programming language"},
					"style_guide": {Type: "string", Description: "Coding style guide to follow"},
				},
				Required: []string{"code"},
			},
		},

		// 5. bug_fix
		{
			Name:        "bug_fix",
			Description: "Analyze and fix bugs in code",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":          {Type: "string", Description: "Code with the bug"},
					"error_message": {Type: "string", Description: "Error message or stack trace"},
					"language":      {Type: "string", Description: "Programming language"},
				},
				Required: []string{"code"},
			},
		},

		// 6. test_generation
		{
			Name:        "test_generation",
			Description: "Generate unit tests for code",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":      {Type: "string", Description: "Source code to test"},
					"language":  {Type: "string", Description: "Programming language"},
					"framework": {Type: "string", Description: "Test framework to use (e.g. pytest, jest)"},
				},
				Required: []string{"code"},
			},
		},

		// 7. documentation_generation
		{
			Name:        "documentation_generation",
			Description: "Generate documentation from code or specifications",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":     {Type: "string", Description: "Code to document"},
					"language": {Type: "string", Description: "Programming language"},
					"format":   {Type: "string", Description: "Documentation format: markdown, rst, godoc, etc."},
				},
				Required: []string{"code"},
			},
		},

		// 8. api_design
		{
			Name:        "api_design",
			Description: "Design RESTful or RPC API endpoints",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"specification": {Type: "string", Description: "API requirements and specification"},
					"style":         {Type: "string", Description: "API style: REST, GraphQL, gRPC"},
					"resources":     {Type: "string", Description: "Resources to model in the API"},
				},
				Required: []string{"specification"},
			},
		},

		// 9. database_schema_design
		{
			Name:        "database_schema_design",
			Description: "Design database schemas and migrations",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"entities":    {Type: "string", Description: "Entities and relationships to model"},
					"db_type":     {Type: "string", Description: "Database type: postgresql, mysql, mongodb, etc."},
					"constraints": {Type: "string", Description: "Performance or design constraints"},
				},
				Required: []string{"entities", "db_type"},
			},
		},

		// 10. architecture_review
		{
			Name:        "architecture_review",
			Description: "Review system architecture for scalability and reliability",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"architecture_desc": {Type: "string", Description: "Description of the architecture"},
					"diagram":           {Type: "string", Description: "Architecture diagram in text format"},
					"concerns":          {Type: "string", Description: "Specific areas of concern"},
				},
				Required: []string{"architecture_desc"},
			},
		},

		// 11. devops_pipeline
		{
			Name:        "devops_pipeline",
			Description: "Generate CI/CD pipeline configuration",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"platform":   {Type: "string", Description: "CI/CD platform: github-actions, gitlab-ci, jenkins"},
					"stages":     {Type: "string", Description: "Pipeline stages: build, test, deploy"},
					"tech_stack": {Type: "string", Description: "Technology stack used by the project"},
				},
				Required: []string{"platform"},
			},
		},

		// 12. docker_compose
		{
			Name:        "docker_compose",
			Description: "Generate Docker and docker-compose configurations",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"services": {Type: "string", Description: "Service definitions"},
					"ports":    {Type: "string", Description: "Port mappings"},
					"volumes":  {Type: "string", Description: "Volume configurations"},
					"networks": {Type: "string", Description: "Network configurations"},
				},
				Required: []string{"services"},
			},
		},

		// 13. kubernetes_manifests
		{
			Name:        "kubernetes_manifests",
			Description: "Generate Kubernetes deployment manifests",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"app_name":  {Type: "string", Description: "Application name"},
					"image":     {Type: "string", Description: "Container image"},
					"replicas":  {Type: "integer", Description: "Number of replicas"},
					"resources": {Type: "string", Description: "Resource requirements"},
				},
				Required: []string{"app_name", "image"},
			},
		},

		// 14. security_audit
		{
			Name:        "security_audit",
			Description: "Audit code or configuration for security vulnerabilities",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"target":   {Type: "string", Description: "Code or config to audit"},
					"scope":    {Type: "string", Description: "Audit scope: owasp-top10, dependency, config"},
					"language": {Type: "string", Description: "Programming language or config format"},
				},
				Required: []string{"target"},
			},
		},

		// 15. performance_optimization
		{
			Name:        "performance_optimization",
			Description: "Analyze and optimize code performance",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"code":           {Type: "string", Description: "Code to optimize"},
					"profiling_data": {Type: "string", Description: "Profiling/bottleneck data"},
					"language":       {Type: "string", Description: "Programming language"},
				},
				Required: []string{"code"},
			},
		},

		// 16. data_analysis
		{
			Name:        "data_analysis",
			Description: "Analyze data and produce insights",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"data_source": {Type: "string", Description: "Path or description of data source"},
					"query":       {Type: "string", Description: "Analysis query or question"},
					"format":      {Type: "string", Description: "Data format: csv, json, sql, etc."},
				},
				Required: []string{"query"},
			},
		},

		// 17. data_visualization
		{
			Name:        "data_visualization",
			Description: "Generate data visualization code and charts",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"data":       {Type: "string", Description: "Data to visualize"},
					"chart_type": {Type: "string", Description: "Chart type: bar, line, scatter, pie, etc."},
					"tool":       {Type: "string", Description: "Visualization tool: matplotlib, echarts, d3, etc."},
				},
				Required: []string{"data", "chart_type"},
			},
		},

		// 18. ml_model_training
		{
			Name:        "ml_model_training",
			Description: "Generate code for training machine learning models",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"task":      {Type: "string", Description: "ML task: classification, regression, clustering"},
					"framework": {Type: "string", Description: "ML framework: pytorch, tensorflow, sklearn"},
					"data_desc": {Type: "string", Description: "Description of training data"},
				},
				Required: []string{"task"},
			},
		},

		// 19. prompt_engineering
		{
			Name:        "prompt_engineering",
			Description: "Optimize prompts for LLM interaction",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"prompt": {Type: "string", Description: "Original prompt to optimize"},
					"goal":   {Type: "string", Description: "Desired outcome or improvement"},
					"model":  {Type: "string", Description: "Target LLM model"},
				},
				Required: []string{"prompt"},
			},
		},

		// 20. rag_pipeline
		{
			Name:        "rag_pipeline",
			Description: "Design and configure RAG (Retrieval-Augmented Generation) pipelines",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"documents_desc": {Type: "string", Description: "Description of documents to index"},
					"embedding":      {Type: "string", Description: "Embedding model to use"},
					"vector_store":   {Type: "string", Description: "Vector store: chroma, pinecone, weaviate"},
				},
				Required: []string{"documents_desc"},
			},
		},

		// 21. debugging_assistant
		{
			Name:        "debugging_assistant",
			Description: "Interactive debugging assistance and root cause analysis",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"logs":    {Type: "string", Description: "Error logs or stack traces"},
					"code":    {Type: "string", Description: "Relevant code snippets"},
					"context": {Type: "string", Description: "System and runtime context"},
				},
				Required: []string{},
			},
		},

		// 22. shell_scripting
		{
			Name:        "shell_scripting",
			Description: "Generate and explain shell scripts for automation",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"task":  {Type: "string", Description: "Task to automate"},
					"shell": {Type: "string", Description: "Shell: bash, zsh, powershell"},
					"os":    {Type: "string", Description: "Target OS: linux, macos, windows"},
				},
				Required: []string{"task"},
			},
		},

		// 23. config_management
		{
			Name:        "config_management",
			Description: "Manage and validate application configuration files",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"format":      {Type: "string", Description: "Config format: yaml, json, toml, env"},
					"schema":      {Type: "string", Description: "Desired schema or specification"},
					"environment": {Type: "string", Description: "Target environment: dev, staging, prod"},
				},
				Required: []string{"format"},
			},
		},

		// 24. regex_generation
		{
			Name:        "regex_generation",
			Description: "Generate and explain regular expressions",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"pattern_desc": {Type: "string", Description: "Description of what to match"},
					"samples":      {Type: "string", Description: "Sample strings to match"},
					"flags":        {Type: "string", Description: "Regex flags: g, i, m, s"},
				},
				Required: []string{"pattern_desc"},
			},
		},

		// 25. git_operations
		{
			Name:        "git_operations",
			Description: "Generate and explain git commands for version control",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"operation":  {Type: "string", Description: "Git operation: rebase, merge, cherry-pick, etc."},
					"branch":     {Type: "string", Description: "Branch name"},
					"repository": {Type: "string", Description: "Repository context"},
				},
				Required: []string{"operation"},
			},
		},

		// 26. dependency_analysis
		{
			Name:        "dependency_analysis",
			Description: "Analyze project dependencies for conflicts and vulnerabilities",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"package_file": {Type: "string", Description: "Path or content of dependency manifest"},
					"ecosystem":    {Type: "string", Description: "Package ecosystem: npm, pip, maven, go-mod"},
					"check_type":   {Type: "string", Description: "Check type: security, licenses, conflicts"},
				},
				Required: []string{"package_file", "ecosystem"},
			},
		},

		// 27. log_analysis
		{
			Name:        "log_analysis",
			Description: "Parse, filter, and analyze log files",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"logs":    {Type: "string", Description: "Raw log content"},
					"pattern": {Type: "string", Description: "Pattern to search for"},
					"source":  {Type: "string", Description: "Log source: nginx, docker, syslog, app"},
				},
				Required: []string{"logs"},
			},
		},

		// 28. i18n_l10n
		{
			Name:        "i18n_l10n",
			Description: "Internationalization and localization support",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"strings":     {Type: "string", Description: "Strings or translation file to process"},
					"source_lang": {Type: "string", Description: "Source language code"},
					"target_lang": {Type: "string", Description: "Target language code"},
				},
				Required: []string{"strings", "target_lang"},
			},
		},

		// 29. ui_ux_review
		{
			Name:        "ui_ux_review",
			Description: "Review UI/UX design for usability and accessibility",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"design_spec": {Type: "string", Description: "Design specification or screenshot description"},
					"platform":    {Type: "string", Description: "Platform: web, mobile, desktop"},
					"checklist":   {Type: "string", Description: "Review checklist: a11y, responsive, ux-heuristics"},
				},
				Required: []string{"design_spec"},
			},
		},

		// 30. data_migration
		{
			Name:        "data_migration",
			Description: "Plan and generate data migration scripts",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"source_db":      {Type: "string", Description: "Source database type and connection"},
					"target_db":      {Type: "string", Description: "Target database type and connection"},
					"schema_mapping": {Type: "string", Description: "Schema mapping specification"},
				},
				Required: []string{"source_db", "target_db"},
			},
		},

		// 31. project_scaffolding
		{
			Name:        "project_scaffolding",
			Description: "Generate project boilerplate and directory structures",
			InputSchema: InputSchema{
				Type: "object",
				Properties: map[string]PropDef{
					"project_type": {Type: "string", Description: "Project type: web-api, cli, library, fullstack"},
					"language":     {Type: "string", Description: "Primary programming language"},
					"framework":    {Type: "string", Description: "Framework to use"},
				},
				Required: []string{"project_type", "language"},
			},
		},
	}

	tr.tools = tools
	for _, t := range tools {
		tr.byName[t.Name] = t
	}
}

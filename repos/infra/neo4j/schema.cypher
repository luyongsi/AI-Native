// Neo4j Knowledge Graph Schema for K14 (Dependency Topology) + K15 (Change Propagation)
// Initialize constraints and indices for efficient querying

// ============================================================================
// CONSTRAINTS
// ============================================================================

// Requirement constraints
CREATE CONSTRAINT req_id_unique IF NOT EXISTS
FOR (r:Requirement) REQUIRE r.req_id IS UNIQUE;

// Service constraints
CREATE CONSTRAINT service_name_unique IF NOT EXISTS
FOR (s:Service) REQUIRE s.name IS UNIQUE;

// Module/File constraints
CREATE CONSTRAINT module_path_unique IF NOT EXISTS
FOR (m:Module) REQUIRE m.path IS UNIQUE;

// API Endpoint constraints
CREATE CONSTRAINT api_endpoint_unique IF NOT EXISTS
FOR (a:APIEndpoint) REQUIRE a.path IS UNIQUE;

// Database table constraints
CREATE CONSTRAINT database_table_unique IF NOT EXISTS
FOR (d:Database) REQUIRE d.name IS UNIQUE;

// Function constraints
CREATE CONSTRAINT function_unique IF NOT EXISTS
FOR (f:Function) REQUIRE f.fqn IS UNIQUE;

// ============================================================================
// INDICES
// ============================================================================

// Requirement indices
CREATE INDEX req_created IF NOT EXISTS
FOR (r:Requirement) ON (r.created_at);

CREATE INDEX req_status IF NOT EXISTS
FOR (r:Requirement) ON (r.status);

// Service indices
CREATE INDEX service_type IF NOT EXISTS
FOR (s:Service) ON (s.type);

CREATE INDEX service_status IF NOT EXISTS
FOR (s:Service) ON (s.status);

// Module indices
CREATE INDEX module_lang IF NOT EXISTS
FOR (m:Module) ON (m.language);

CREATE INDEX module_updated IF NOT EXISTS
FOR (m:Module) ON (m.updated_at);

// APIEndpoint indices
CREATE INDEX api_method IF NOT EXISTS
FOR (a:APIEndpoint) ON (a.http_method);

CREATE INDEX api_status IF NOT EXISTS
FOR (a:APIEndpoint) ON (a.status);

// Database indices
CREATE INDEX db_type IF NOT EXISTS
FOR (d:Database) ON (d.type);

// Function indices
CREATE INDEX func_lang IF NOT EXISTS
FOR (f:Function) ON (f.language);

// ============================================================================
// NODE TYPES DOCUMENTATION
// ============================================================================
//
// Requirement:
//   - req_id: Unique requirement identifier (UUID)
//   - title: Requirement title
//   - description: Full description
//   - status: active | archived | deprecated
//   - created_at: ISO 8601 timestamp
//   - updated_at: ISO 8601 timestamp
//   - complexity: low | medium | high | critical
//
// Service:
//   - name: Service name (unique)
//   - type: backend | frontend | gateway | messaging | storage
//   - status: active | inactive | deprecated
//   - description: Service description
//   - owner: Team/owner name
//   - created_at: ISO 8601 timestamp
//
// Module:
//   - path: File path (unique)
//   - name: Module/file name
//   - language: python | typescript | java | go | rust | sql
//   - type: controller | service | model | util | config | test
//   - updated_at: ISO 8601 timestamp
//
// APIEndpoint:
//   - path: API path (unique)
//   - http_method: GET | POST | PUT | DELETE | PATCH
//   - description: Endpoint description
//   - status: active | deprecated
//   - response_type: JSON schema identifier
//
// Database:
//   - name: Table name (unique)
//   - type: table | view | materialized_view
//   - schema: Database schema name
//   - owner_service: Service that owns this table
//
// Function:
//   - fqn: Fully qualified name (unique)
//   - name: Function name
//   - language: Implementation language
//   - returns: Return type
//   - is_async: boolean
//
// ============================================================================
// RELATIONSHIP TYPES
// ============================================================================
//
// DEFINES:        Requirement -> APIEndpoint (requirement defines this endpoint)
// CREATES:        Requirement -> Database (requirement creates this table)
// DEPENDS_ON:     * -> * (general dependency with type field)
// IMPLEMENTS:     Module -> APIEndpoint (module implements endpoint)
// QUERIES:        Module -> Database (module queries table)
// CALLS:          Function -> Function (function calls another)
// BELONGS_TO:     Module -> Service (module belongs to service)
// OPERATES_IN:    Service -> Service (orchestration/dependency)
//
// ============================================================================

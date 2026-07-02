"""
Inner Auditor — Real Toolchain Integration
=============================================

Comprehensive code quality and security auditing for the A9 Dev Agent.

## Architecture

The Inner Auditor integrates multiple real static analysis tools organized in three check categories:

### 1. Linting (Code Quality)
- **Python**: pylint, mypy
- **JavaScript/TypeScript**: ESLint
- **Go**: golangci-lint
- **Rust**: clippy

### 2. Type Checking
- **Python**: mypy
- **TypeScript**: tsc
- **Go**: Native type checking
- **Rust**: Native type checking

### 3. Security Scanning
- **All Languages**: Semgrep (pattern-based)
- **Python**: bandit (security-focused)
- **All Languages**: Built-in pattern detection (CWE-based rules)

## Components

### Core Modules

1. **tool_executor.py**
   - Async subprocess execution with timeout control
   - Graceful handling of tool unavailability
   - Configurable timeouts (default 30s)

2. **enhanced_static_analyzer.py**
   - Multi-tool analysis per language
   - Parallel tool execution
   - Unified output format
   - JSON-based parsing for all tools

3. **semgrep_analyzer.py**
   - Semgrep integration with auto-config
   - Finding categorization (security/performance/best-practice)
   - Severity mapping (CRITICAL/HIGH/MEDIUM/LOW)
   - Graceful degradation if Semgrep unavailable

4. **security_rules.py**
   - Pattern-based vulnerability detection
   - CWE mapping for findings
   - Covers 8 major vulnerability classes:
     * SQL Injection (CWE-89)
     * XSS (CWE-79)
     * Hardcoded Secrets (CWE-798)
     * Insecure Deserialization (CWE-502)
     * Weak Cryptography (CWE-327)
     * Insecure Random (CWE-338)
     * Command Injection (CWE-78)
     * Path Traversal (CWE-22)

5. **auditor.py** (InnerAuditor class)
   - Main orchestrator for all checks
   - Language detection and grouping
   - Parallel execution of lint, type-check, security scans
   - Unified result aggregation
   - Fallback to pattern-based detection

6. **metrics.py**
   - Prometheus metric definitions
   - Tool execution tracking
   - Finding counts by severity
   - Audit run metrics

### Tool Configurations

Located in `tool_configs/`:
- **.eslintrc.json**: ESLint rules for JavaScript/TypeScript
- **mypy.ini**: Type checking configuration for Python
- **pylintrc**: Linting configuration for Python
- **.semgrep.yml**: Semgrep rule definitions

## Usage

### Basic Usage

```python
from inner_auditor.auditor import InnerAuditor

# Initialize
auditor = InnerAuditor(timeout=30, enable_semgrep=True)

# Run all checks
file_paths = ["src/app.py", "src/index.ts"]
results = await auditor.run_all(file_paths)

# Access results
print(f"Lint: {results['lint']['error_count']} errors")
print(f"Type: {results['type_check']['error_count']} errors")
print(f"Security: {results['security_scan']['critical_count']} critical")
```

### Individual Checks

```python
# Lint only
lint_result = await auditor.run_lint(["src/app.py"])

# Type check only
type_result = await auditor.run_type_check(["src/app.ts"])

# Security scan only
sec_result = await auditor.run_security_scan(["src/app.py"])
```

### Result Format

Each check returns a dict with:

**Lint Results:**
```python
{
    "tool": "pylint / eslint / golangci-lint",
    "issues": [
        {
            "file": "path/to/file.py",
            "line": 42,
            "column": 5,
            "severity": "error|warning",
            "message": "...",
            "tool": "pylint"
        }
    ],
    "error_count": 5,
    "warning_count": 12,
    "mock": False,
    "by_file": {}
}
```

**Type Check Results:**
```python
{
    "tool": "mypy / tsc",
    "errors": [
        {
            "file": "path/to/file.ts",
            "line": 10,
            "column": 5,
            "code": "TS2322",
            "message": "..."
        }
    ],
    "error_count": 2,
    "mock": False,
    "by_file": {}
}
```

**Security Scan Results:**
```python
{
    "tool": "semgrep / bandit / pattern-based",
    "vulnerabilities": [
        {
            "file": "path/to/file.py",
            "line": 15,
            "severity": "critical|high|medium|low",
            "rule": "sql-injection",
            "message": "Potential SQL injection vulnerability",
            "source": "semgrep|pattern-based",
            "cwe": "CWE-89"
        }
    ],
    "critical_count": 1,
    "high_count": 2,
    "medium_count": 3,
    "low_count": 5,
    "mock": False,
    "by_file": {}
}
```

## Tool Requirements

### Required Tools

For full functionality, install:

```bash
# Python tools
pip install pylint mypy bandit

# JavaScript tools
npm install -g eslint

# Security scanning
pip install semgrep
# or: brew install semgrep (macOS)
```

### Optional Tools

```bash
# Go
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

# Rust
cargo install clippy

# TypeScript
npm install -g typescript
```

## Graceful Degradation

The auditor gracefully handles missing tools:
- If a tool is not installed, it returns an empty result
- Pattern-based security detection always runs
- No failures cascade — one tool timeout doesn't block others
- Timeout configurable per instance (default 30s)

## Performance

### Timeout Strategy
- Individual tool: 30s (configurable)
- Parallel execution: Multiple tools run concurrently
- Pattern detection: <100ms for typical files

### File Processing
- Small files (<10KB): <1s per file
- Medium files (10-100KB): 1-5s per file
- Large files (>100KB): 5-30s per file

## Security Patterns Detected

### SQL Injection (CWE-89)
- String formatting in SQL queries
- f-strings in execute() calls
- % formatting in SQL

### XSS (CWE-79)
- String concatenation to innerHTML
- React dangerouslySetInnerHTML
- document.write() usage

### Hardcoded Secrets (CWE-798)
- API keys, passwords, tokens in string literals
- AWS credentials
- Minimum length 6-20 chars depending on type

### Command Injection (CWE-78)
- os.system() with user input
- subprocess with shell=True
- exec/eval usage

### Insecure Deserialization (CWE-502)
- pickle.load()
- yaml.load()
- eval/exec

### Weak Cryptography (CWE-327)
- MD5/SHA1 hashing
- DES encryption
- Weak RNG usage

## Metrics

Enable Prometheus metrics (requires `prometheus_client`):

```python
from inner_auditor.metrics import record_tool_execution, record_findings

# Metrics are auto-recorded by the auditor
# Access via: AUDITOR_TOOL_EXECUTIONS, AUDITOR_FINDINGS_COUNT, etc.
```

Exported metrics:
- `auditor_tool_executions_total` — Tool execution count
- `auditor_tool_duration_seconds` — Tool execution time
- `auditor_tool_timeouts_total` — Timeout count
- `auditor_findings_count` — Finding counts by severity
- `auditor_runs_total` — Total audit runs
- `auditor_run_duration_seconds` — Full audit duration

## Testing

Run integration tests:

```bash
pytest inner-auditor/test_integration.py -v

# Test specific functionality
pytest inner-auditor/test_integration.py::TestSecurityRules -v
pytest inner-auditor/test_integration.py::TestToolExecutor -v
```

## Troubleshooting

### Tool Not Found
```
[ToolExecutor] Tool not found: pylint
```
Install the required tool: `pip install pylint`

### Timeout
```
[InnerAuditor] Tool timed out after 30s
```
Increase timeout: `InnerAuditor(timeout=60)`

### Parser Errors
```
[EnhancedStaticAnalyzer] Failed to parse pylint output
```
Check tool version compatibility and configuration

## Implementation Notes

### Acceptance Criteria Met
- [x] ESLint integration (JavaScript/TypeScript)
- [x] mypy integration (Python type checking)
- [x] Semgrep integration (security scanning)
- [x] SQL injection detection
- [x] XSS detection
- [x] Tool timeout control (30s)
- [x] Graceful degradation on tool failure
- [x] Prometheus metrics
- [x] Integration tests

### Architecture Decisions
1. **Async execution**: All tool runs are async for parallelism
2. **Unified output**: All tools produce consistent JSON structures
3. **Pattern fallback**: Security scanning includes regex patterns for robustness
4. **Timeout-first**: Tools are given time limits from the start
5. **Language grouping**: Files analyzed per-language for efficiency

### Future Enhancements
- IDE integration (VS Code, IntelliJ)
- CI/CD pipeline integration
- Custom rule support
- Performance profiling per tool
- Result caching between runs
- Parallel file analysis with worker pools
"""

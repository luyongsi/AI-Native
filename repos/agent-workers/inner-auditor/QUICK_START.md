"""
Quick Start Guide — Inner Auditor Real Toolchain
================================================

Get up and running with the new Inner Auditor in 5 minutes.

## Installation

### 1. Install Required Tools

```bash
# Python tools
pip install pylint mypy bandit

# JavaScript tools
npm install -g eslint

# Security scanning (optional but recommended)
pip install semgrep
# macOS: brew install semgrep
# Linux: pip install semgrep
```

### 2. Verify Installation

```bash
pylint --version
mypy --version
eslint --version
semgrep --version
```

## Basic Usage

### Simple Example

```python
import asyncio
from inner_auditor.auditor import InnerAuditor

async def main():
    # Initialize auditor
    auditor = InnerAuditor(timeout=30, enable_semgrep=True)
    
    # Run all checks
    files = ["src/app.py", "src/index.ts", "src/utils.js"]
    results = await auditor.run_all(files)
    
    # Display results
    print(f"Lint Errors: {results['lint']['error_count']}")
    print(f"Type Errors: {results['type_check']['error_count']}")
    print(f"Security Issues: {results['security_scan']['critical_count']}")

# Run
asyncio.run(main())
```

### Individual Checks

```python
# Lint only
lint_results = await auditor.run_lint(["src/app.py"])
print(f"Lint: {lint_results['error_count']} errors")

# Type check only
type_results = await auditor.run_type_check(["src/app.ts"])
print(f"Types: {type_results['error_count']} errors")

# Security scan only
sec_results = await auditor.run_security_scan(["src/app.py"])
print(f"Security: {sec_results['critical_count']} critical")
```

## Integration with A9 Dev Agent

Add to your workflow:

```python
from inner_auditor.auditor import InnerAuditor

class DevAgent:
    def __init__(self):
        self.auditor = InnerAuditor(timeout=30)
    
    async def submit_code(self, file_paths: list, changes: str):
        """Submit code for review."""
        # Run quality checks
        audit_results = await self.auditor.run_all(file_paths)
        
        # Make decision
        if audit_results['security_scan']['critical_count'] > 0:
            return {"decision": "rejected", "reason": "Security issues found"}
        
        if audit_results['lint']['error_count'] > 0:
            return {"decision": "review_required", "reason": "Lint errors"}
        
        if audit_results['type_check']['error_count'] > 0:
            return {"decision": "review_required", "reason": "Type errors"}
        
        return {"decision": "approved", "details": audit_results}
```

## Understanding Results

### Lint Results

```python
result = await auditor.run_lint(["app.py"])

# Structure
{
    "tool": "pylint / eslint",
    "issues": [
        {
            "file": "app.py",
            "line": 42,
            "column": 5,
            "severity": "error",
            "message": "Unused variable 'x'",
            "tool": "pylint"
        }
    ],
    "error_count": 1,      # Total errors
    "warning_count": 3,    # Total warnings
    "mock": False,         # Real tool (not mock)
    "by_file": {}          # Detailed per-file breakdown
}
```

### Type Check Results

```python
result = await auditor.run_type_check(["app.ts"])

# Structure
{
    "tool": "mypy / tsc",
    "errors": [
        {
            "file": "app.ts",
            "line": 10,
            "column": 5,
            "code": "TS2322",
            "message": "Type 'string' is not assignable to type 'number'"
        }
    ],
    "error_count": 1,
    "mock": False,
    "by_file": {}
}
```

### Security Scan Results

```python
result = await auditor.run_security_scan(["app.py"])

# Structure
{
    "tool": "semgrep / pattern-based",
    "vulnerabilities": [
        {
            "file": "app.py",
            "line": 15,
            "severity": "critical",
            "rule": "sql-injection",
            "message": "Potential SQL injection vulnerability",
            "source": "semgrep",
            "cwe": "CWE-89"
        }
    ],
    "critical_count": 1,
    "high_count": 0,
    "medium_count": 0,
    "low_count": 0,
    "mock": False,
    "by_file": {}
}
```

## Common Patterns

### Check Specific File Type

```python
# Lint only Python files
python_files = [f for f in all_files if f.endswith('.py')]
results = await auditor.run_lint(python_files)
```

### Increase Timeout for Large Files

```python
# Increase timeout to 60 seconds
auditor = InnerAuditor(timeout=60)
```

### Disable Semgrep (for faster results)

```python
# Use only pattern-based security scanning
auditor = InnerAuditor(enable_semgrep=False)
```

### Check Language Support

```python
# Check what language a file is detected as
auditor = InnerAuditor()
language = auditor._detect_language("myfile.xyz")
print(f"Language: {language}")

# Supported: python, javascript, typescript, go, rust, 
#            java, cpp, c, csharp, ruby, php, unknown
```

## Troubleshooting

### "Tool not found: pylint"

```bash
# Install it
pip install pylint

# Or check it's in PATH
which pylint
python -m pylint --version
```

### "Tool timed out after 30s"

```python
# Increase timeout
auditor = InnerAuditor(timeout=60)
```

### "Failed to parse output"

```bash
# Check tool version
pylint --version  # Should be 2.x or 3.x
eslint --version  # Should be 7.x or 8.x
```

### No results (tools returning empty)

```python
# Check files exist
from pathlib import Path
for f in files:
    if not Path(f).exists():
        print(f"File not found: {f}")
```

## Performance Tips

1. **Group by language**: Auditor does this automatically
2. **Parallel execution**: All 3 checks run concurrently
3. **Skip unavailable tools**: Auditor handles gracefully
4. **Use pattern-based**: Falls back if Semgrep unavailable
5. **Batch files**: Run multiple files together

```python
# Good - processes in parallel
results = await auditor.run_all(["app.py", "index.ts", "utils.js"])

# Also good - tools run per-language in parallel
results = await auditor.run_all(["file1.py", "file2.py", "file3.py"])
```

## Metrics

Enable Prometheus metrics (requires `pip install prometheus_client`):

```python
from inner_auditor.metrics import AUDITOR_RUNS, AUDITOR_FINDINGS_COUNT

# Metrics are automatically recorded by InnerAuditor

# Access metrics
total_runs = AUDITOR_RUNS.labels(status="success")._value.get()
```

## Next Steps

1. Read full documentation: `INTEGRATION_GUIDE.md`
2. Run tests: `pytest test_integration.py -v`
3. Review implementation: `IMPLEMENTATION_SUMMARY.md`
4. Configure tools: `tool_configs/`

## File Structure

```
inner-auditor/
├── auditor.py                 # Main orchestrator
├── tool_executor.py           # Subprocess management
├── enhanced_static_analyzer.py # Multi-tool analysis
├── semgrep_analyzer.py        # Semgrep integration
├── security_rules.py          # Pattern detection
├── metrics.py                 # Prometheus metrics
├── test_integration.py        # Tests
├── QUICK_START.md             # This file
├── INTEGRATION_GUIDE.md       # Full documentation
├── IMPLEMENTATION_SUMMARY.md  # Technical details
└── tool_configs/              # Tool configurations
```

## Support

For issues or questions:
1. Check INTEGRATION_GUIDE.md troubleshooting section
2. Review test_integration.py for usage examples
3. Check tool versions and compatibility
4. Verify files exist and are readable
"""

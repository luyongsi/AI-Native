# A12 Security Scanner - Implementation Guide

## Overview

A12 Security Scanner integrates real security scanning tools (Bandit, npm audit, Semgrep) to provide comprehensive security analysis of code changes. It replaces the simplified mock implementation with production-ready tool integration.

## Architecture

### Components

1. **SecurityScanner** (`security_scanner.py`)
   - Unified interface for multiple security tools
   - Supports Python (Bandit + Semgrep), JavaScript/TypeScript (npm audit + Semgrep)
   - Parallel scanning of multiple files
   - Graceful degradation if tools unavailable

2. **CWEMapper** (`cwe_mapper.py`)
   - Maps CWE IDs to standard severity levels (CRITICAL, HIGH, MEDIUM, LOW)
   - Calculates risk scores (0-10 scale)
   - Generates security decisions and recommendations
   - Categorizes findings by severity, tool, and CWE

3. **CrossModuleImpactAnalyzer** (updated `a12_impact_analyzer.py`)
   - Phase 2: Pattern-based impact analysis
   - Phase 3: Neo4j graph-based analysis (K15)
   - Phase 4: Security scanning (new)
   - Merged decision based on all three phases

### Security Tools Integrated

#### Bandit (Python)
- **Purpose**: Security vulnerability scanning for Python code
- **CWE Coverage**: SQL Injection (CWE-89), OS Command Injection (CWE-78), Deserialization (CWE-502), etc.
- **Output**: JSON format with severity, confidence, line numbers
- **Command**: `bandit -r <file> -f json`

#### npm audit (JavaScript/TypeScript)
- **Purpose**: Dependency vulnerability detection
- **CWE Coverage**: All registered CVEs for dependencies
- **Output**: JSON format with package names, versions, severity
- **Command**: `npm audit --json`

#### Semgrep (Cross-language)
- **Purpose**: Pattern-based static analysis
- **Custom Rules**: `semgrep-rules/custom.yaml` (14 security rules)
- **Coverage**: XSS, SSRF, hardcoded credentials, path traversal, weak crypto, etc.
- **Output**: JSON format with check IDs, messages, locations

## Installation

### Prerequisites
- Python 3.8+
- Node.js 14+ (for npm audit)
- pip (Python package manager)

### Quick Start

```bash
# Make install script executable
chmod +x a12/install_tools.sh

# Run installation
./a12/install_tools.sh
```

This installs:
- Bandit: `pip install bandit`
- Semgrep: `pip install semgrep`
- npm audit: (included with Node.js)

### Manual Installation

```bash
# Install Python tools
pip install bandit semgrep

# Verify installations
bandit --version
semgrep --version
npm audit --version
```

## Usage

### Basic Scanning

```python
import asyncio
from a12.security_scanner import SecurityScanner

async def scan_files():
    scanner = SecurityScanner(timeout=60)
    
    # Scan Python file
    result = await scanner.scan_python("app.py")
    print(f"Findings: {result['findings']}")
    print(f"Summary: {result['summary']}")
    
    # Scan JavaScript file
    result = await scanner.scan_javascript("index.js")
    
    # Scan multiple files in parallel
    results = await scanner.scan_multiple([
        "src/main.py",
        "src/utils.js",
        "package.json"
    ])

asyncio.run(scan_files())
```

### Security Analysis with CWE Mapping

```python
from a12.cwe_mapper import CWEMapper
from a12.security_scanner import SecurityScanner

async def analyze_security():
    scanner = SecurityScanner()
    mapper = CWEMapper()
    
    # Scan files
    result = await scanner.scan_multiple(["app.py", "index.js"])
    findings = result["all_findings"]
    
    # Generate security report
    report = mapper.generate_report(findings)
    
    print(f"Risk Score: {report['risk_score']}/10")
    print(f"Risk Level: {report['risk_level']}")
    print(f"Decision: {report['decision']}")
    print(f"Critical Issues: {report['critical_count']}")
    print(f"Recommendation: {report['recommendation']}")

asyncio.run(analyze_security())
```

### Integration with A12 Impact Analyzer

```python
from a12_impact_analyzer import CrossModuleImpactAnalyzer

async def full_analysis():
    analyzer = CrossModuleImpactAnalyzer(
        use_neo4j=True,
        enable_security_scan=True
    )
    
    # Analyze code changes with security scanning
    result = await analyzer.analyze(
        diff=["src/api/auth.py", "src/utils.js", "package.json"],
        req_id="req-12345"
    )
    
    # Results include security findings
    print(f"Overall Decision: {result.get('overall_decision')}")
    print(f"Security Risk Score: {result.get('security_risk_score')}")
    print(f"Security Findings: {result.get('security_findings')}")
    print(f"Analysis Phases: {result.get('analysis_phases')}")  # ["phase2", "phase3", "phase4"]
    
    await analyzer.close()

asyncio.run(full_analysis())
```

## Findings Format

### Standard Finding Structure

All tools output findings in normalized format:

```python
{
    "tool": "bandit|semgrep|npm_audit",
    "severity": "CRITICAL|HIGH|MEDIUM|LOW",
    "file": "path/to/file.py",
    "line": 42,
    "message": "Description of vulnerability",
    "cwe": "CWE-89",  # Common Weakness Enumeration
    # Additional tool-specific fields
}
```

### Bandit Findings
```python
{
    "tool": "bandit",
    "severity": "CRITICAL",
    "confidence": "HIGH",
    "cwe": "CWE-78",
    "test_id": "B602",
    "test_name": "shell_injection",
    "file": "app.py",
    "line": 42,
    "message": "Use of system calls with shell=True"
}
```

### npm audit Findings
```python
{
    "tool": "npm_audit",
    "severity": "CRITICAL",
    "package": "lodash",
    "installed_version": "4.17.15",
    "vulnerable_versions": "<4.17.20",
    "url": "https://nvd.nist.gov/...",
    "cvss": {"score": 7.4},
    "cwe": ["CWE-1321"],
    "message": "Prototype Pollution in lodash"
}
```

### Semgrep Findings
```python
{
    "tool": "semgrep",
    "severity": "CRITICAL",
    "check_id": "hardcoded-credentials",
    "file": "config.py",
    "line": 10,
    "column": 5,
    "message": "Hardcoded API key detected",
    "metadata": {"cwe": "CWE-798"}
}
```

## Risk Scoring Algorithm

Risk scores are calculated on a 0-10 scale:

- **CRITICAL**: +3.0 points per finding
- **HIGH**: +2.0 points per finding
- **MEDIUM**: +1.0 point per finding
- **LOW**: +0.5 points per finding
- **Score capped at 10.0**

### Risk Level Mapping

| Score | Level | Decision |
|-------|-------|----------|
| 8.0-10.0 | CRITICAL | REJECT |
| 6.0-7.9 | HIGH | CONDITIONAL/REVIEW |
| 3.0-5.9 | MEDIUM | REVIEW |
| 0.1-2.9 | LOW | APPROVE |
| 0.0 | NONE | APPROVE |

## CWE Coverage

### Mapped CWE IDs (20+ total)

| CWE | Severity | Description |
|-----|----------|-------------|
| CWE-89 | CRITICAL | SQL Injection |
| CWE-78 | CRITICAL | OS Command Injection |
| CWE-94 | CRITICAL | Code Injection |
| CWE-798 | CRITICAL | Hard-coded Credentials |
| CWE-79 | HIGH | Cross-site Scripting (XSS) |
| CWE-22 | HIGH | Path Traversal |
| CWE-502 | HIGH | Insecure Deserialization |
| CWE-918 | HIGH | Server-Side Request Forgery (SSRF) |
| CWE-611 | HIGH | Improper XML External Entity |
| CWE-327 | MEDIUM | Weak Cryptography |
| CWE-338 | MEDIUM | Weak Random Number Generation |
| CWE-259 | MEDIUM | Hard-coded Password |
| CWE-295 | MEDIUM | Improper Certificate Validation |
| CWE-352 | MEDIUM | Cross-Site Request Forgery (CSRF) |
| CWE-319 | LOW | Cleartext Transmission |

## Semgrep Custom Rules

Located in `a12/semgrep-rules/custom.yaml` (14 rules):

1. **hardcoded-api-key** (CWE-798): Detects hardcoded API keys
2. **sql-injection-risk** (CWE-89): Identifies SQL injection patterns
3. **command-injection** (CWE-78): Detects command injection vulnerabilities
4. **xss-vulnerability** (CWE-79): Identifies XSS vulnerabilities
5. **path-traversal** (CWE-22): Detects path traversal issues
6. **insecure-deserialization** (CWE-502): Flags unsafe deserialization
7. **weak-cryptography** (CWE-327): Identifies weak crypto algorithms
8. **hardcoded-credentials** (CWE-798): Detects hardcoded secrets
9. **ssrf-vulnerability** (CWE-918): Identifies SSRF risks
10. **missing-auth-check** (CWE-306): Detects unauthenticated endpoints
11. **insecure-random** (CWE-338): Flags insecure random generation
12. **unvalidated-redirect** (CWE-601): Detects unvalidated redirects

## Testing

### Run Unit Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest a12/test_security_scanner.py -v

# Run specific test class
pytest a12/test_security_scanner.py::TestSecurityScanner -v

# Run with coverage
pytest a12/test_security_scanner.py --cov=a12
```

### Test Coverage

- Bandit findings parser (2 test cases)
- npm audit findings parser (2 test cases)
- Semgrep findings converter (2 test cases)
- CWE mapping (6 test cases)
- Risk scoring (4 test cases)
- Findings categorization (1 test case)
- Report generation (1 test case)
- End-to-end analysis (1 test case)

## Error Handling

### Graceful Degradation

If a security tool is unavailable:

```python
# Tool not installed
{
    "success": False,
    "findings": [],
    "tool_unavailable": True,
    "error": "Bandit not installed"
}

# Tool timed out
{
    "success": False,
    "findings": [],
    "error": "Bandit timed out after 60s"
}
```

### Exception Handling

```python
try:
    result = await scanner.scan_python("app.py")
except Exception as e:
    logger.error(f"Scan failed: {e}")
    # Handle gracefully - return empty findings
```

## Configuration

### Custom Semgrep Rules Path

```python
scanner = SecurityScanner(
    custom_rules_path="/path/to/rules.yaml"
)
```

### Tool Timeout

```python
scanner = SecurityScanner(timeout=120)  # 2 minutes
```

### Enable/Disable Security Scanning

```python
analyzer = CrossModuleImpactAnalyzer(
    use_neo4j=True,
    enable_security_scan=True  # Default: True
)
```

## Performance

### Execution Times (Typical)

| Tool | File Size | Time |
|------|-----------|------|
| Bandit | 1MB Python | 2-5s |
| npm audit | package.json | 3-10s |
| Semgrep | 1MB Python | 1-3s |
| All three | Mixed 5 files | 5-15s |

### Parallel Scanning

Files are scanned in parallel using asyncio:

```python
# Scans all 4 files concurrently, not sequentially
result = await scanner.scan_multiple([
    "file1.py",
    "file2.py",
    "file3.js",
    "package.json"
])
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
- name: A12 Security Scan
  run: |
    python -c "
    import asyncio
    from a12.security_scanner import SecurityScanner
    from a12.cwe_mapper import CWEMapper
    
    async def scan():
        scanner = SecurityScanner()
        mapper = CWEMapper()
        result = await scanner.scan_multiple(['src/'])
        report = mapper.generate_report(result['all_findings'])
        
        if report['risk_score'] > 7.0:
            exit(1)  # Fail build
    
    asyncio.run(scan())
    "
```

## Troubleshooting

### Bandit Not Found

```bash
# Install Bandit
pip install bandit

# Verify
which bandit
bandit --version
```

### npm audit Fails

```bash
# Ensure Node.js installed
node --version
npm --version

# Update npm
npm install -g npm@latest

# Install dependencies first
npm install
```

### Semgrep Issues

```bash
# Install/upgrade Semgrep
pip install --upgrade semgrep

# Test with simple file
semgrep --config=auto simple.py
```

### Timeout Issues

Increase timeout for large files:

```python
scanner = SecurityScanner(timeout=180)  # 3 minutes
```

## Security Considerations

1. **Tool Installation**: Install tools in isolated environments
2. **File Access**: Scanner reads file contents; ensure proper permissions
3. **Output Handling**: Security findings may contain sensitive paths
4. **Tool Binaries**: Verify tool versions and sources
5. **Dependency Versions**: Keep Bandit, Semgrep, and Node updated

## Future Enhancements

- Integration with additional tools (Pylint, ESLint security plugins)
- Custom severity mappings per organization
- Security baseline tracking over time
- Automated remediation suggestions
- Integration with SAST/DAST tools
- Machine learning-based risk prediction

## References

- CWE List: https://cwe.mitre.org/
- Bandit Documentation: https://bandit.readthedocs.io/
- Semgrep Documentation: https://semgrep.dev/docs/
- npm audit Documentation: https://docs.npmjs.com/cli/audit

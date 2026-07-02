#!/bin/bash
# A12 Security Tools Installation Script
# Installs Bandit, Semgrep, and configures npm audit

set -e

echo "=================================================="
echo "A12 Security Scanner - Tool Installation"
echo "=================================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Check Python availability
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed"
    exit 1
fi
print_status "Python 3 found: $(python3 --version)"

# Check pip availability
if ! command -v pip3 &> /dev/null; then
    print_error "pip3 is not installed"
    exit 1
fi
print_status "pip3 found"

# Install Bandit
echo ""
echo "Installing Bandit (Python security scanner)..."
if pip3 install bandit --quiet 2>/dev/null; then
    print_status "Bandit installed successfully"
    bandit --version
else
    print_warning "Bandit installation may have encountered issues, but continuing..."
fi

# Install Semgrep
echo ""
echo "Installing Semgrep (static analysis)..."
if pip3 install semgrep --quiet 2>/dev/null; then
    print_status "Semgrep installed successfully"
    semgrep --version
else
    print_warning "Semgrep installation may have encountered issues, but continuing..."
fi

# Check npm availability
echo ""
if command -v npm &> /dev/null; then
    print_status "npm found: $(npm --version)"
    print_status "npm audit is included with npm (no separate installation needed)"
else
    print_warning "npm is not installed - JavaScript dependency scanning will be unavailable"
    print_warning "To use npm audit, install Node.js from https://nodejs.org/"
fi

# Verification
echo ""
echo "=================================================="
echo "Verifying installations..."
echo "=================================================="

# Verify Bandit
echo -n "Bandit: "
if command -v bandit &> /dev/null; then
    print_status "Available"
else
    print_error "Not found or not in PATH"
fi

# Verify Semgrep
echo -n "Semgrep: "
if command -v semgrep &> /dev/null; then
    print_status "Available"
else
    print_error "Not found or not in PATH"
fi

# Verify npm audit
echo -n "npm audit: "
if command -v npm &> /dev/null; then
    print_status "Available"
else
    print_warning "npm not available"
fi

echo ""
echo "=================================================="
echo "Installation complete!"
echo "=================================================="
echo ""
echo "Summary:"
echo "  - Bandit: Python security vulnerability scanner"
echo "  - Semgrep: Static analysis with custom rules"
echo "  - npm audit: JavaScript/TypeScript dependency auditor"
echo ""
echo "Next steps:"
echo "  1. Run tests: python -m pytest a12/test_security_scanner.py"
echo "  2. Check configuration: cat a12/semgrep-rules/custom.yaml"
echo "  3. Test with sample files: python -c 'from a12.security_scanner import SecurityScanner'"
echo ""

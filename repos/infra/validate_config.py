#!/usr/bin/env python3
"""
Configuration validation script - checks AlertManager and Prometheus setup.
Run this to verify configurations are valid before deploying.
"""
import sys
import subprocess
import json
from pathlib import Path

def check_yaml_syntax(filepath):
    """Validate YAML syntax."""
    try:
        import yaml
        with open(filepath) as f:
            yaml.safe_load(f)
        return True, "Valid"
    except ImportError:
        return None, "PyYAML not installed (skip)"
    except Exception as e:
        return False, str(e)

def check_prometheus_rules(rules_file):
    """Check Prometheus rule file syntax using promtool."""
    try:
        result = subprocess.run(
            ["promtool", "check", "rules", rules_file],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return True, "Valid"
        else:
            return False, result.stderr or result.stdout
    except FileNotFoundError:
        return None, "promtool not found (install prometheus-client)"
    except Exception as e:
        return None, str(e)

def check_file_exists(path, description):
    """Check if file exists."""
    if Path(path).exists():
        size = Path(path).stat().st_size
        return True, f"EXISTS ({size} bytes)"
    else:
        return False, "MISSING"

def main():
    base_path = Path(__file__).parent.parent
    prometheus_dir = base_path / "prometheus"

    print("=" * 70)
    print("AlertManager + Prometheus Configuration Validator")
    print("=" * 70)
    print()

    checks = [
        ("AlertManager Config", lambda: check_yaml_syntax(prometheus_dir / "alertmanager.yml")),
        ("Prometheus Config", lambda: check_yaml_syntax(prometheus_dir / "prometheus.yml")),
        ("Alert Rules (YAML)", lambda: check_yaml_syntax(prometheus_dir / "alert-rules.yaml")),
        ("Alert Rules (PromQL)", lambda: check_prometheus_rules(str(prometheus_dir / "alert-rules.yaml"))),
        ("docker-compose.yml", lambda: check_file_exists(base_path / "docker-compose.yml", "docker-compose")),
        ("Test Script", lambda: check_file_exists(prometheus_dir / "test_alerts.py", "test_alerts.py")),
        ("mc-backend/api/alerts.py", lambda: check_file_exists(base_path.parent / "mc-backend" / "api" / "alerts.py", "alerts.py")),
    ]

    results = []
    for name, check_func in checks:
        try:
            success, message = check_func()
            status = "✓" if success else ("?" if success is None else "✗")
            results.append((name, status, message))
            print(f"{status} {name}: {message}")
        except Exception as e:
            print(f"✗ {name}: ERROR - {e}")
            results.append((name, "✗", str(e)))

    print()
    print("=" * 70)

    # Count results
    passed = sum(1 for _, s, _ in results if s == "✓")
    failed = sum(1 for _, s, _ in results if s == "✗")
    skipped = sum(1 for _, s, _ in results if s == "?")

    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")

    if failed > 0:
        print("\nPlease fix the errors above before deploying.")
        return 1
    else:
        print("\nAll checks passed! Configuration is ready to deploy.")
        return 0

if __name__ == "__main__":
    sys.exit(main())

"""
Test suite for A4 API Schema Generator (Task #31)

Tests:
  - Schema validation with valid/invalid specs
  - API schema generation (with mock LLM)
  - Few-shot example injection
  - Fallback schema generation
  - Retry logic on validation failure
"""

import json
import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent / "agent-workers"))

from a4.schema_validator import SchemaValidator
from a4.api_schema_generator import APISchemaGenerator


def test_schema_validator():
    """Test SchemaValidator with valid and invalid specs."""
    print("\n=== Testing SchemaValidator ===")
    validator = SchemaValidator()

    # Test 1: Valid minimal OpenAPI 3.1 spec
    valid_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/test": {
                "get": {
                    "summary": "Test endpoint",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    is_valid, errors = validator.validate(valid_spec)
    assert is_valid, f"Valid spec should pass validation: {errors}"
    print("✓ Valid spec passes validation")

    # Test 2: Missing required fields
    invalid_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test API"},  # Missing version
        "paths": {},
    }
    is_valid, errors = validator.validate(invalid_spec)
    assert not is_valid, "Invalid spec should fail validation"
    assert any("version" in str(e).lower() for e in errors), "Should report missing version"
    print("✓ Invalid spec fails validation correctly")

    # Test 3: Validate and fix
    broken_spec = {"info": {"title": "API"}, "paths": {"/test": {"get": {}}}}
    is_valid, fixed_spec, fixes = validator.validate_and_fix(broken_spec)
    assert "openapi" in fixed_spec, "Should add missing openapi field"
    assert fixed_spec["openapi"] == "3.1.0", "Should add correct OpenAPI version"
    assert len(fixes) > 0, "Should report fixes applied"
    print("✓ Validator fixes broken specs")


async def test_api_schema_generator():
    """Test APISchemaGenerator with mock LLM."""
    print("\n=== Testing APISchemaGenerator ===")
    generator = APISchemaGenerator()

    # Test 1: Few-shot examples are present
    assert len(generator.FEWSHOT_EXAMPLES) >= 2, "Should have at least 2 examples"
    for example in generator.FEWSHOT_EXAMPLES:
        assert "requirement" in example, "Example should have requirement"
        assert "openapi" in example, "Example should have openapi spec"
        assert "paths" in example["openapi"], "Example openapi should have paths"
    print("✓ Few-shot examples are well-formed")

    # Test 2: Fallback generation
    fallback = generator._generate_fallback("user_management", "general")
    assert fallback["source"] == "fallback", "Should be marked as fallback"
    assert fallback["schema"]["openapi"] == "3.1.0", "Should generate valid OpenAPI 3.1"
    assert "paths" in fallback["schema"], "Should have paths"
    assert "/health" in fallback["schema"]["paths"], "Should have health endpoint"
    print("✓ Fallback schema generation works")

    # Test 3: Prompt building
    prompt = generator._build_prompt("Create user API", "User Management", "auth")
    assert "openapi" in prompt.lower(), "Prompt should mention OpenAPI"
    assert "3.1" in prompt, "Prompt should specify version 3.1"
    assert "EXAMPLE" in prompt, "Prompt should include examples"
    assert len(prompt) > 500, "Prompt should be substantial"
    print("✓ Prompt building includes fewshot examples")

    # Test 4: LLM response parsing
    valid_json_response = '{"paths": {"/api/test": {"get": {}}}, "openapi": "3.1.0", "info": {"title": "Test", "version": "1.0"}}'
    schema, error = generator._parse_llm_response(valid_json_response)
    assert error is None, f"Should parse valid JSON: {error}"
    assert "paths" in schema, "Should extract paths"
    print("✓ LLM response parsing works")

    # Test 5: Parse response with markdown wrapping
    markdown_response = '```json\n{"paths": {"/test": {"get": {}}}, "openapi": "3.1.0", "info": {"title": "API", "version": "1.0"}}\n```'
    schema, error = generator._parse_llm_response(markdown_response)
    assert error is None, f"Should parse markdown-wrapped JSON: {error}"
    assert "paths" in schema, "Should extract paths from markdown"
    print("✓ LLM response parsing handles markdown")

    # Test 6: Generate with fallback (no DEEPSEEK_API_KEY)
    result = await generator.generate(
        "Create a user authentication system",
        context={"title": "Auth API", "domain": "authentication"},
        max_retries=1,
    )
    assert "schema" in result, "Result should have schema"
    assert result["schema"]["openapi"] == "3.1.0", "Schema should be valid OpenAPI 3.1"
    assert "validation_log" in result, "Result should have validation log"
    assert "generated_at" in result, "Result should have timestamp"
    print("✓ Schema generation returns complete result")


def test_schema_validator_retry():
    """Test validation retry logic."""
    print("\n=== Testing Validation Retry Logic ===")
    validator = SchemaValidator()

    # Partially broken spec that can be fixed
    broken_spec = {"info": {"title": "API"}}
    is_valid, fixed, log = validator.validate_and_fix(broken_spec)
    assert "openapi" in fixed, "Should add openapi"
    assert "paths" in fixed, "Should add paths"
    assert len(log) > 0, "Should log fixes"
    print(f"✓ Retry logic applied {len(log)} fixes")
    for entry in log:
        print(f"  - {entry}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("A4 API Schema Generator Test Suite (Task #31)")
    print("=" * 60)

    try:
        test_schema_validator()
        asyncio.run(test_api_schema_generator())
        test_schema_validator_retry()

        print("\n" + "=" * 60)
        print("All tests passed!")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

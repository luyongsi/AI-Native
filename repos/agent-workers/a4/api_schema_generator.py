"""
A4 Sub-module: API Schema Generator

Generates OpenAPI 3.1 specifications from requirement text using LLM with few-shot prompting.
Includes schema validation and automatic retry with fixes on validation failure.
"""

import json
import logging
import os
import asyncio
from typing import Optional, Dict, Any, List, Tuple, Callable
from datetime import datetime, timezone

from .schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


class APISchemaGenerator:
    """Generates OpenAPI 3.1 specifications from requirement text using LLM."""

    # Few-shot examples for prompt injection
    FEWSHOT_EXAMPLES = [
        {
            "requirement": "User authentication and profile management system",
            "openapi": {
                "info": {"title": "User API", "version": "1.0.0", "description": "User authentication and management"},
                "paths": {
                    "/auth/login": {
                        "post": {
                            "tags": ["auth"],
                            "summary": "User login",
                            "operationId": "login",
                            "requestBody": {
                                "required": True,
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["email", "password"],
                                            "properties": {
                                                "email": {"type": "string", "format": "email", "example": "user@example.com"},
                                                "password": {"type": "string", "format": "password", "example": "secure_pwd"},
                                            },
                                        }
                                    }
                                },
                            },
                            "responses": {
                                "200": {
                                    "description": "Login successful",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "token": {"type": "string", "example": "eyJhbGc..."},
                                                    "user": {"$ref": "#/components/schemas/User"},
                                                },
                                            }
                                        }
                                    },
                                },
                                "401": {"description": "Invalid credentials"},
                            },
                        }
                    },
                    "/users/{id}": {
                        "get": {
                            "tags": ["users"],
                            "summary": "Get user by ID",
                            "parameters": [
                                {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string", "format": "uuid"},
                                }
                            ],
                            "responses": {
                                "200": {
                                    "description": "User details",
                                    "content": {
                                        "application/json": {
                                            "schema": {"$ref": "#/components/schemas/User"}
                                        }
                                    },
                                }
                            },
                        }
                    },
                },
                "components": {
                    "schemas": {
                        "User": {
                            "type": "object",
                            "required": ["id", "email"],
                            "properties": {
                                "id": {"type": "string", "format": "uuid"},
                                "email": {"type": "string", "format": "email"},
                                "name": {"type": "string"},
                                "created_at": {"type": "string", "format": "date-time"},
                            },
                        }
                    }
                },
            },
        },
        {
            "requirement": "Product catalog and order management",
            "openapi": {
                "info": {"title": "E-Commerce API", "version": "1.0.0", "description": "Product and order management"},
                "paths": {
                    "/products": {
                        "get": {
                            "tags": ["products"],
                            "summary": "List all products",
                            "parameters": [
                                {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                            ],
                            "responses": {
                                "200": {
                                    "description": "Product list",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "data": {
                                                        "type": "array",
                                                        "items": {"$ref": "#/components/schemas/Product"},
                                                    },
                                                    "total": {"type": "integer"},
                                                },
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    },
                    "/orders": {
                        "post": {
                            "tags": ["orders"],
                            "summary": "Create order",
                            "requestBody": {
                                "required": True,
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/OrderCreate"}
                                    }
                                },
                            },
                            "responses": {
                                "201": {
                                    "description": "Order created",
                                    "content": {
                                        "application/json": {
                                            "schema": {"$ref": "#/components/schemas/Order"}
                                        }
                                    },
                                }
                            },
                        }
                    },
                },
                "components": {
                    "schemas": {
                        "Product": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "format": "uuid"},
                                "name": {"type": "string"},
                                "price": {"type": "number", "format": "float"},
                                "stock": {"type": "integer"},
                            },
                        },
                        "Order": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "format": "uuid"},
                                "items": {"type": "array", "items": {"$ref": "#/components/schemas/OrderItem"}},
                                "total": {"type": "number", "format": "float"},
                                "status": {"type": "string", "enum": ["pending", "completed", "cancelled"]},
                            },
                        },
                        "OrderCreate": {
                            "type": "object",
                            "required": ["items"],
                            "properties": {
                                "items": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/OrderItem"},
                                },
                            },
                        },
                        "OrderItem": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "string", "format": "uuid"},
                                "quantity": {"type": "integer", "minimum": 1},
                            },
                        },
                    }
                },
            },
        },
    ]

    def __init__(self, llm_caller: Callable | None = None):
        self.validator = SchemaValidator()
        self._llm = llm_caller  # external call_llm injected by A4SpecWriter
        self._context: Dict[str, Any] = {}

    async def generate(
        self,
        requirement_text: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Generate OpenAPI 3.1 specification from requirement text.

        Uses LLM with few-shot prompting and validates the generated schema.
        Retries up to max_retries times if validation fails.

        Args:
            requirement_text: The requirement description.
            context: Optional context dict with title, domain, etc.
            max_retries: Maximum number of retry attempts on validation failure.

        Returns:
            A complete OpenAPI 3.1 spec dict with validation metadata.
        """
        context = context or {}
        self._context = context
        title = context.get("title", "Generated API")
        domain = context.get("domain", "general")

        logger.info(f"Generating OpenAPI 3.1 spec for domain={domain}, title={title}")

        # Build prompt with few-shot examples (and rework feedback if present)
        rework_feedback = context.get("rework_feedback", "")
        prompt = self._build_prompt(requirement_text, title, domain, rework_feedback)

        # Call LLM
        llm_response = await self._call_llm(prompt)
        if not llm_response:
            logger.warning("LLM call failed, returning fallback schema")
            return self._generate_fallback(title, domain)

        # Parse and validate
        schema, parse_error = self._parse_llm_response(llm_response)
        if parse_error:
            logger.error(f"Failed to parse LLM response: {parse_error}")
            return self._generate_fallback(title, domain)

        # Validate and retry on failure
        is_valid, schema, validation_log = await self._validate_and_retry(schema, max_retries)

        result = {
            "openapi": "3.1.0",
            "schema": schema,
            "validation_passed": is_valid,
            "validation_log": validation_log,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "llm",
        }

        logger.info(f"OpenAPI schema generation completed: valid={is_valid}")
        return result

    async def _validate_and_retry(
        self, schema: Dict[str, Any], max_retries: int
    ) -> Tuple[bool, Dict[str, Any], List[str]]:
        """Validate schema and retry with fixes if needed.

        Args:
            schema: The schema to validate.
            max_retries: Maximum number of retries.

        Returns:
            A tuple of (is_valid, schema, validation_log).
        """
        validation_log: List[str] = []

        for attempt in range(max_retries + 1):
            is_valid, validation_errors = self.validator.validate(schema)

            if is_valid:
                validation_log.append(f"✓ Validation passed on attempt {attempt + 1}")
                return True, schema, validation_log

            validation_log.append(f"✗ Attempt {attempt + 1}: {len(validation_errors)} errors - {', '.join(validation_errors[:2])}")

            if attempt < max_retries:
                # Attempt automatic fix
                is_valid, fixed_schema, fixes = self.validator.validate_and_fix(schema)
                if is_valid:
                    validation_log.append(f"  Fixed with: {', '.join(fixes)}")
                    return True, fixed_schema, validation_log
                else:
                    schema = fixed_schema
                    validation_log.append(f"  Applied fixes but still invalid")

        validation_log.append(f"✗ Failed validation after {max_retries + 1} attempts")
        return False, schema, validation_log

    def _build_prompt(self, requirement_text: str, title: str, domain: str, rework_feedback: str = "") -> str:
        """Build the LLM prompt with few-shot examples."""
        fewshot_text = self._format_fewshot_examples()

        feedback_section = ""
        if rework_feedback:
            feedback_section = f"""

PREVIOUS REVIEW FEEDBACK (must address critical and major issues):
{rework_feedback}
---
"""

        prompt = f"""You are an expert API architect. Generate a complete, valid OpenAPI 3.1 specification from the following requirement.

REQUIREMENT:
Title: {title}
Domain: {domain}
Description: {requirement_text}
{feedback_section}
EXAMPLES OF GOOD API DESIGNS:
{fewshot_text}

INSTRUCTIONS:
1. Generate a complete OpenAPI 3.1 specification with:
   - Valid openapi version "3.1.0"
   - info object with title, version, description
   - paths object with at least one endpoint
   - components/schemas with domain-appropriate data models
   - Proper HTTP methods (GET, POST, PUT, DELETE, etc.)
   - Request/response schemas with examples
   - Security definitions if applicable

2. Follow REST conventions:
   - Use plural nouns for collections (/users, /products)
   - Use specific IDs for single resources (/users/{{id}})
   - Use appropriate HTTP methods (GET for read, POST for create, PUT for update, DELETE for delete)
   - Return appropriate status codes (200, 201, 400, 404, etc.)

3. Schema requirements:
   - All paths must have responses defined
   - POST/PUT operations must have requestBody with schema
   - All schema properties must have types
   - Use $ref for complex schema reuse
   - Include examples in schemas

4. Output ONLY valid JSON, no markdown, no explanations.
   Start with {{ and end with }}, nothing else.
"""
        return prompt

    def _format_fewshot_examples(self) -> str:
        """Format few-shot examples for the prompt."""
        examples_text = ""
        for i, example in enumerate(self.FEWSHOT_EXAMPLES, 1):
            examples_text += f"\nEXAMPLE {i}: {example['requirement']}\n"
            examples_text += "```json\n"
            examples_text += json.dumps(example["openapi"], indent=2)
            examples_text += "\n```\n"
        return examples_text

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """Call the LLM API via the injected callable (or fallback to direct httpx)."""
        if self._llm:
            try:
                return await self._llm(
                    [{"role": "user", "content": prompt}],
                    task_type="openapi_gen",
                    temperature=0.2,
                    max_tokens=4000,
                    req_id=self._context.get("req_id", ""),
                    workflow_id=self._context.get("workflow_id", ""),
                )
            except Exception as e:
                logger.error(f"Injected LLM call failed: {e}")

        # Fallback: direct call (only if no callable injected, transitional)
        DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
        if not DEEPSEEK_API_KEY:
            logger.warning("DEEPSEEK_API_KEY not configured, LLM call skipped")
            return None

        try:
            import httpx

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{os.environ.get('DEEPSEEK_BASE_URL', 'https://uniapi.ruijie.com.cn')}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606"),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 4000,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    def _parse_llm_response(self, response: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """Parse JSON from LLM response, handling markdown wrapping."""
        try:
            content = response.strip()

            # Remove markdown code blocks if present
            if content.startswith("```"):
                # Extract content between backticks
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

            # Remove 'json' prefix if present
            if content.startswith("json"):
                content = content[4:].strip()

            schema = json.loads(content)
            return schema, None
        except json.JSONDecodeError as e:
            return {}, f"JSON parse error: {str(e)}"
        except Exception as e:
            return {}, f"Parse error: {str(e)}"

    def _generate_fallback(self, title: str, domain: str) -> Dict[str, Any]:
        """Generate a minimal valid OpenAPI spec as fallback."""
        return {
            "openapi": "3.1.0",
            "schema": {
                "openapi": "3.1.0",
                "info": {
                    "title": title,
                    "version": "0.1.0",
                    "description": f"Auto-generated API specification for {domain}",
                },
                "paths": {
                    "/health": {
                        "get": {
                            "tags": ["system"],
                            "summary": "Health check",
                            "responses": {
                                "200": {
                                    "description": "Service is healthy",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "status": {"type": "string", "example": "ok"},
                                                },
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    },
                    f"/{domain.lower()}": {
                        "get": {
                            "tags": [domain],
                            "summary": f"List all {domain} records",
                            "responses": {
                                "200": {
                                    "description": f"List of {domain} records",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "data": {"type": "array", "items": {"type": "object"}},
                                                    "total": {"type": "integer"},
                                                },
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    },
                },
                "components": {
                    "schemas": {
                        "Error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "validation_passed": False,
            "validation_log": ["Using fallback schema due to LLM error"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "fallback",
        }

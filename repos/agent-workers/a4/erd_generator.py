"""
A4 Sub-module: ERD Generator

Generates Entity-Relationship Diagrams and DDL from requirement text using LLM.
- Uses few-shot prompting with database design examples
- Generates Mermaid ERD syntax
- Produces PostgreSQL DDL statements
- Validates DDL and retries on failure
- Detects existing tables for incremental schema updates
"""

import json
import logging
import os
import asyncio
import re
from typing import Optional, Dict, Any, List, Tuple, Callable
from datetime import datetime, timezone

from .ddl_validator import DDLValidator

logger = logging.getLogger(__name__)


class ERDGenerator:
    """Generates ERD diagrams and DDL from requirement text using LLM."""

    # Few-shot examples for prompt injection
    FEWSHOT_EXAMPLES = [
        {
            "requirement": "用户管理系统，需要记录用户基本信息、认证信息、个人资料",
            "erd": (
                "erDiagram\n"
                "  USERS ||--o{ USER_PROFILES : has\n"
                "  USERS ||--o{ USER_SESSIONS : creates\n"
                "  USER_PROFILES {\n"
                "    UUID id PK\n"
                "    UUID user_id FK\n"
                "    string first_name\n"
                "    string last_name\n"
                "    string bio\n"
                "    string avatar_url\n"
                "  }\n"
                "  USERS {\n"
                "    UUID id PK\n"
                "    string email UK\n"
                "    string password_hash\n"
                "    string username UK\n"
                "    boolean is_active\n"
                "    timestamp created_at\n"
                "    timestamp updated_at\n"
                "  }\n"
                "  USER_SESSIONS {\n"
                "    UUID id PK\n"
                "    UUID user_id FK\n"
                "    string token\n"
                "    timestamp expires_at\n"
                "    timestamp created_at\n"
                "  }"
            ),
            "ddl": (
                "CREATE TABLE users (\n"
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                "  email VARCHAR(255) NOT NULL UNIQUE,\n"
                "  username VARCHAR(100) NOT NULL UNIQUE,\n"
                "  password_hash VARCHAR(255) NOT NULL,\n"
                "  is_active BOOLEAN DEFAULT true NOT NULL,\n"
                "  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,\n"
                "  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL\n"
                ");\n\n"
                "CREATE TABLE user_profiles (\n"
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                "  user_id UUID NOT NULL,\n"
                "  first_name VARCHAR(100),\n"
                "  last_name VARCHAR(100),\n"
                "  bio TEXT,\n"
                "  avatar_url VARCHAR(512),\n"
                "  CONSTRAINT fk_user_profiles_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE\n"
                ");\n\n"
                "CREATE TABLE user_sessions (\n"
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                "  user_id UUID NOT NULL,\n"
                "  token VARCHAR(512) NOT NULL UNIQUE,\n"
                "  expires_at TIMESTAMP WITH TIME ZONE NOT NULL,\n"
                "  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,\n"
                "  CONSTRAINT fk_user_sessions_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE\n"
                ");\n\n"
                "CREATE INDEX idx_users_email ON users(email);\n"
                "CREATE INDEX idx_user_profiles_user_id ON user_profiles(user_id);\n"
                "CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);\n"
                "CREATE INDEX idx_user_sessions_token ON user_sessions(token);"
            ),
            "entities": [
                {"name": "users", "primary_key": "id"},
                {"name": "user_profiles", "primary_key": "id"},
                {"name": "user_sessions", "primary_key": "id"},
            ],
            "relationships": [
                {"from": "users", "to": "user_profiles", "type": "one_to_many"},
                {"from": "users", "to": "user_sessions", "type": "one_to_many"},
            ],
        },
        {
            "requirement": "电商平台，包括产品目录、购物车、订单、库存管理",
            "erd": (
                "erDiagram\n"
                "  PRODUCTS ||--o{ ORDER_ITEMS : orders\n"
                "  PRODUCTS ||--o{ CART_ITEMS : contains\n"
                "  PRODUCTS ||--o{ INVENTORY : tracks\n"
                "  ORDERS ||--o{ ORDER_ITEMS : has\n"
                "  USERS ||--o{ ORDERS : places\n"
                "  USERS ||--o{ CARTS : owns\n"
                "  CARTS ||--o{ CART_ITEMS : contains\n"
                "  PRODUCTS {\n"
                "    UUID id PK\n"
                "    string name\n"
                "    text description\n"
                "    decimal price\n"
                "    string sku UK\n"
                "  }\n"
                "  ORDERS {\n"
                "    UUID id PK\n"
                "    UUID user_id FK\n"
                "    decimal total_amount\n"
                "    string status\n"
                "    timestamp created_at\n"
                "  }\n"
                "  ORDER_ITEMS {\n"
                "    UUID id PK\n"
                "    UUID order_id FK\n"
                "    UUID product_id FK\n"
                "    integer quantity\n"
                "    decimal unit_price\n"
                "  }"
            ),
            "ddl": (
                "CREATE TABLE products (\n"
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                "  name VARCHAR(255) NOT NULL,\n"
                "  description TEXT,\n"
                "  price DECIMAL(12,2) NOT NULL,\n"
                "  sku VARCHAR(100) NOT NULL UNIQUE,\n"
                "  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL\n"
                ");\n\n"
                "CREATE TABLE orders (\n"
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                "  user_id UUID NOT NULL,\n"
                "  total_amount DECIMAL(12,2) NOT NULL,\n"
                "  status VARCHAR(50) NOT NULL DEFAULT 'pending',\n"
                "  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,\n"
                "  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,\n"
                "  CONSTRAINT fk_orders_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE\n"
                ");\n\n"
                "CREATE TABLE order_items (\n"
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                "  order_id UUID NOT NULL,\n"
                "  product_id UUID NOT NULL,\n"
                "  quantity INTEGER NOT NULL,\n"
                "  unit_price DECIMAL(12,2) NOT NULL,\n"
                "  CONSTRAINT fk_order_items_order_id FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,\n"
                "  CONSTRAINT fk_order_items_product_id FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT\n"
                ");\n\n"
                "CREATE INDEX idx_products_sku ON products(sku);\n"
                "CREATE INDEX idx_orders_user_id ON orders(user_id);\n"
                "CREATE INDEX idx_order_items_order_id ON order_items(order_id);"
            ),
            "entities": [
                {"name": "products", "primary_key": "id"},
                {"name": "orders", "primary_key": "id"},
                {"name": "order_items", "primary_key": "id"},
            ],
            "relationships": [
                {"from": "products", "to": "order_items", "type": "one_to_many"},
                {"from": "orders", "to": "order_items", "type": "one_to_many"},
            ],
        },
    ]

    def __init__(self, llm_caller: Callable | None = None):
        self.validator = DDLValidator()
        self._llm = llm_caller  # external call_llm injected by A4SpecWriter
        self._context: Dict[str, Any] = {}

    async def generate(
        self,
        requirement_text: str,
        context: Optional[Dict[str, Any]] = None,
        existing_tables: Optional[List[str]] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Generate ERD and DDL from requirement text.

        Uses LLM with few-shot prompting and validates the generated DDL.
        Retries up to max_retries times if validation fails.

        Args:
            requirement_text: The requirement description.
            context: Optional context dict with title, domain, etc.
            existing_tables: Optional list of existing table names for incremental schema.
            max_retries: Maximum number of retry attempts on validation failure.

        Returns:
            A dict with erd_mermaid, ddl, entities, relationships, and metadata.
        """
        context = context or {}
        self._context = context
        title = context.get("title", "Generated Database")
        domain = context.get("domain", "general")
        existing_tables = existing_tables or []

        logger.info(
            f"Generating ERD for domain={domain}, title={title}, "
            f"existing_tables={len(existing_tables)}"
        )

        # Build prompt with few-shot examples
        prompt = self._build_prompt(
            requirement_text, title, domain, existing_tables
        )

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

        # Validate DDL and retry on failure
        is_valid, ddl, validation_log = await self._validate_and_retry(
            schema.get("ddl", ""), max_retries
        )

        # Build result
        result = {
            "erd_mermaid": schema.get("erd_mermaid", ""),
            "ddl": ddl,
            "entities": schema.get("entities", []),
            "relationships": schema.get("relationships", []),
            "validation_passed": is_valid,
            "validation_log": validation_log,
            "is_incremental": len(existing_tables) > 0,
            "existing_tables": existing_tables,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "llm",
        }

        logger.info(
            f"ERD generation completed: valid={is_valid}, "
            f"entities={len(schema.get('entities', []))} "
            f"relationships={len(schema.get('relationships', []))}"
        )
        return result

    async def _validate_and_retry(
        self, ddl: str, max_retries: int
    ) -> Tuple[bool, str, List[str]]:
        """Validate DDL and retry with fixes if needed.

        Args:
            ddl: The DDL to validate.
            max_retries: Maximum number of retries.

        Returns:
            A tuple of (is_valid, ddl, validation_log).
        """
        validation_log: List[str] = []

        for attempt in range(max_retries + 1):
            is_valid, errors = self.validator.validate(ddl)

            if is_valid:
                validation_log.append(f"✓ Validation passed on attempt {attempt + 1}")
                return True, ddl, validation_log

            error_summary = ", ".join(errors[:2]) if errors else "Unknown error"
            validation_log.append(f"✗ Attempt {attempt + 1}: {len(errors)} errors - {error_summary}")

            if attempt < max_retries:
                # Attempt simple automatic fixes
                fixed_ddl = self._attempt_fix(ddl, errors)
                if fixed_ddl != ddl:
                    ddl = fixed_ddl
                    validation_log.append(f"  Applied fixes")
                    continue

        validation_log.append(f"✗ Failed validation after {max_retries + 1} attempts")
        return False, ddl, validation_log

    def _attempt_fix(self, ddl: str, errors: List[str]) -> str:
        """Attempt to fix common DDL errors."""
        fixed = ddl

        # Fix common issues
        for error in errors:
            if "unbalanced parentheses" in error.lower():
                # Try to balance parentheses
                fixed = self._balance_parentheses(fixed)
            elif "foreign key" in error.lower() and "does not exist" in error.lower():
                # Try to identify and comment out problematic FKs
                logger.debug(f"Attempting to fix: {error}")

        return fixed

    def _balance_parentheses(self, ddl: str) -> str:
        """Attempt to balance parentheses in DDL."""
        open_count = ddl.count("(")
        close_count = ddl.count(")")

        if open_count > close_count:
            ddl += ")" * (open_count - close_count)
        elif close_count > open_count:
            # This is harder to fix, just log
            logger.warning("More closing than opening parentheses")

        return ddl

    def _build_prompt(
        self,
        requirement_text: str,
        title: str,
        domain: str,
        existing_tables: List[str],
    ) -> str:
        """Build the LLM prompt with few-shot examples."""
        fewshot_text = self._format_fewshot_examples()

        existing_tables_text = (
            f"Existing tables: {', '.join(existing_tables)}\n"
            "For existing tables, generate ALTER TABLE statements instead of CREATE TABLE.\n"
            if existing_tables
            else ""
        )

        prompt = f"""You are an expert database architect. Generate a complete ERD and PostgreSQL DDL from the following requirement.

REQUIREMENT:
Title: {title}
Domain: {domain}
Description: {requirement_text}

{existing_tables_text}

EXAMPLES OF GOOD DATABASE DESIGNS:
{fewshot_text}

INSTRUCTIONS:
1. Generate a Mermaid ERD diagram using erDiagram syntax showing:
   - Entity names and relationships
   - Primary keys (PK) and foreign keys (FK)
   - Unique keys (UK) if applicable
   - Cardinality (one-to-one, one-to-many, many-to-many)

2. Generate complete PostgreSQL DDL with:
   - CREATE TABLE statements with proper column definitions
   - PRIMARY KEY constraints
   - FOREIGN KEY constraints with ON DELETE CASCADE or RESTRICT
   - UNIQUE constraints where needed
   - Appropriate indexes on FK and frequently queried columns
   - Timestamps (created_at, updated_at) for audit trails
   - UUID primary keys with gen_random_uuid() default

3. Use consistent naming:
   - Table names in plural lowercase (users, products, orders)
   - Column names in lowercase with underscores
   - Foreign key columns named as <table>_id
   - Constraint names as fk_<table>_<column>, idx_<table>_<column>

4. Output ONLY valid JSON, no markdown, no explanations.
   Start with {{ and end with }}, nothing else.

JSON SCHEMA:
{{
  "erd_mermaid": "erDiagram content...",
  "ddl": "SQL CREATE/ALTER TABLE statements...",
  "entities": [
    {{"name": "table_name", "primary_key": "id"}}
  ],
  "relationships": [
    {{"from": "table1", "to": "table2", "type": "one_to_many"}}
  ]
}}"""
        return prompt

    def _format_fewshot_examples(self) -> str:
        """Format few-shot examples for the prompt."""
        examples_text = ""
        for i, example in enumerate(self.FEWSHOT_EXAMPLES, 1):
            examples_text += f"\nEXAMPLE {i}: {example['requirement']}\n"
            examples_text += "ERD:\n```\n"
            examples_text += example["erd"]
            examples_text += "\n```\n"
            examples_text += "DDL:\n```sql\n"
            examples_text += example["ddl"]
            examples_text += "\n```\n"
        return examples_text

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """Call the LLM API via the injected callable (or fallback to direct httpx)."""
        if self._llm:
            try:
                return await self._llm(
                    [{"role": "user", "content": prompt}],
                    task_type="erd_gen",
                    temperature=0.2,
                    max_tokens=3000,
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
                        "max_tokens": 6000,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    def _parse_llm_response(
        self, response: str
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Parse JSON from LLM response, handling markdown wrapping."""
        try:
            content = response.strip()

            # Remove markdown code blocks if present
            if content.startswith("```"):
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
        """Generate a minimal valid ERD and DDL as fallback."""
        table_name = f"{domain.lower()}_records"

        erd_mermaid = (
            f"erDiagram\n"
            f"  {table_name.upper()} {{\n"
            f"    UUID id PK\n"
            f"    string title\n"
            f"    timestamp created_at\n"
            f"    timestamp updated_at\n"
            f"  }}"
        )

        ddl = (
            f"CREATE TABLE {table_name} (\n"
            f"  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
            f"  title VARCHAR(255) NOT NULL,\n"
            f"  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,\n"
            f"  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL\n"
            f");\n\n"
            f"CREATE INDEX idx_{table_name}_created_at ON {table_name}(created_at DESC);"
        )

        return {
            "erd_mermaid": erd_mermaid,
            "ddl": ddl,
            "entities": [{"name": table_name, "primary_key": "id"}],
            "relationships": [],
            "validation_passed": True,
            "validation_log": ["Using fallback schema due to LLM error"],
            "is_incremental": False,
            "existing_tables": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "fallback",
        }

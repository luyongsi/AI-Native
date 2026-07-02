"""Few-shot examples for agent retry injection.

Provides task-specific examples to inject into agent context when
the circuit breaker escalates to FEW_SHOT level.
"""

import logging

logger = logging.getLogger(__name__)


# Few-shot examples indexed by agent_id and task_type
FEW_SHOT_EXAMPLES = {
    # A4: Spec Writer (API Schema Generation)
    "A4": {
        "api_schema": [
            {
                "requirement": "User authentication endpoint for login",
                "context": "REST API for SaaS platform",
                "output": {
                    "endpoint": "/auth/login",
                    "method": "POST",
                    "requestBody": {
                        "required": ["username", "password"],
                        "properties": {
                            "username": {"type": "string", "description": "User email or username"},
                            "password": {"type": "string", "description": "User password"}
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Login successful",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "token": {"type": "string"},
                                    "expires_in": {"type": "integer"},
                                    "user": {"type": "object"}
                                }
                            }
                        },
                        "401": {"description": "Invalid credentials"}
                    }
                }
            },
            {
                "requirement": "User registration endpoint",
                "context": "REST API for SaaS platform",
                "output": {
                    "endpoint": "/auth/register",
                    "method": "POST",
                    "requestBody": {
                        "required": ["email", "password", "name"],
                        "properties": {
                            "email": {"type": "string", "format": "email"},
                            "password": {"type": "string", "minLength": 8},
                            "name": {"type": "string"}
                        }
                    },
                    "responses": {
                        "201": {"description": "User created successfully"},
                        "400": {"description": "Invalid input"}
                    }
                }
            },
            {
                "requirement": "List users with pagination",
                "context": "REST API for user management",
                "output": {
                    "endpoint": "/users",
                    "method": "GET",
                    "parameters": {
                        "page": {"type": "integer", "default": 1},
                        "limit": {"type": "integer", "default": 20, "maximum": 100}
                    },
                    "responses": {
                        "200": {
                            "description": "List of users",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "users": {"type": "array"},
                                    "total": {"type": "integer"},
                                    "page": {"type": "integer"}
                                }
                            }
                        }
                    }
                }
            }
        ]
    },
    # A9: Dev Agent (Code Generation)
    "A9": {
        "code_generation": [
            {
                "requirement": "Implement user registration function with password hashing",
                "context": "Python backend, async function",
                "language": "python",
                "output": """async def register_user(username: str, email: str, password: str) -> dict:
    \"\"\"Register a new user with hashed password.\"\"\"
    import hashlib
    import secrets

    # Validate input
    if not username or len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if not email or "@" not in email:
        raise ValueError("Invalid email")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    # Hash password with salt
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)

    # Store in database
    user_id = await db.execute(
        "INSERT INTO users (username, email, password_hash, salt) VALUES (?, ?, ?, ?)",
        (username, email, hashed.hex(), salt)
    )

    return {"user_id": user_id, "username": username, "email": email}"""
            },
            {
                "requirement": "Create a database connection pool manager",
                "context": "Python, async, PostgreSQL",
                "language": "python",
                "output": """import asyncpg

class DatabasePool:
    \"\"\"Manage PostgreSQL connection pool.\"\"\"

    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.pool = None

    async def initialize(self):
        \"\"\"Create connection pool.\"\"\"
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=self.min_size,
            max_size=self.max_size,
            command_timeout=60
        )

    async def execute(self, query: str, *args):
        \"\"\"Execute query and return results.\"\"\"
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def close(self):
        \"\"\"Close connection pool.\"\"\"
        if self.pool:
            await self.pool.close()"""
            },
            {
                "requirement": "Implement rate limiting middleware",
                "context": "Python FastAPI",
                "language": "python",
                "output": """from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
from datetime import datetime, timedelta

class RateLimitMiddleware(BaseHTTPMiddleware):
    \"\"\"Rate limiting middleware for FastAPI.\"\"\"

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)

        # Clean old requests
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if req_time > cutoff
        ]

        # Check rate limit
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"}
            )

        self.requests[client_ip].append(now)
        return await call_next(request)"""
            }
        ]
    }
}


def get_few_shot_examples(agent_id: str, task_type: str = None, count: int = 3) -> list:
    """Get few-shot examples for an agent.

    Args:
        agent_id: Agent identifier (e.g., 'A4', 'A9')
        task_type: Task type within the agent (e.g., 'api_schema', 'code_generation')
        count: Number of examples to return (default 3)

    Returns:
        List of few-shot examples, limited to *count*
    """
    if agent_id not in FEW_SHOT_EXAMPLES:
        logger.debug(f"No few-shot examples available for agent_id={agent_id}")
        return []

    agent_examples = FEW_SHOT_EXAMPLES[agent_id]

    if task_type is None:
        # Return all examples across all task types
        all_examples = []
        for examples in agent_examples.values():
            all_examples.extend(examples)
        return all_examples[:count]

    if task_type not in agent_examples:
        logger.debug(
            f"No few-shot examples for agent_id={agent_id} task_type={task_type}"
        )
        return []

    examples = agent_examples[task_type]
    return examples[:count]


def inject_few_shot_into_context(context: dict, agent_id: str, task_type: str = None) -> dict:
    """Inject few-shot examples into agent execution context.

    Args:
        context: Agent execution context
        agent_id: Agent identifier
        task_type: Task type (optional)

    Returns:
        Updated context with 'few_shot_examples' key
    """
    examples = get_few_shot_examples(agent_id, task_type, count=3)
    if examples:
        context["few_shot_examples"] = examples
        logger.info(
            f"Injected {len(examples)} few-shot examples for agent_id={agent_id}"
        )
    return context

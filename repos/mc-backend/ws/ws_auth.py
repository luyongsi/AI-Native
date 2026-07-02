"""
Mission Control Backend - WebSocket JWT Authentication
Validates JWT tokens during WebSocket handshake.

Supports both HS256 (internal) and RS256 (MCP Gateway) tokens.
"""
import os
import time
import jwt

JWT_SECRET = os.environ.get("JWT_SECRET", "mc-dev-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
MCP_JWT_PUBLIC_KEY = os.environ.get("MCP_JWT_PUBLIC_KEY", "")


def verify_token(token: str) -> dict | None:
    """Verify a JWT token and return its payload. Returns None if invalid.

    Tries HS256 with JWT_SECRET first, then RS256 with MCP_JWT_PUBLIC_KEY if available.
    """
    # Try HS256 (internal tokens)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        pass  # fall through to try MCP key

    # Try RS256 (MCP Gateway-issued tokens)
    if MCP_JWT_PUBLIC_KEY:
        try:
            payload = jwt.decode(token, MCP_JWT_PUBLIC_KEY, algorithms=["RS256"])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    return None


def verify_mcp_token(token: str) -> dict | None:
    """Verify a token specifically as an MCP Gateway-issued RS256 token.

    Uses MCP_JWT_PUBLIC_KEY if set, falls back to JWT_SECRET for dev.
    """
    if not MCP_JWT_PUBLIC_KEY:
        return None

    try:
        payload = jwt.decode(token, MCP_JWT_PUBLIC_KEY, algorithms=["RS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_token(user_id: str, role: str = "viewer") -> str:
    """Create a JWT token for development/testing purposes."""
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400,  # 24h
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

"""FastAPI routes for Context Builder service."""

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from pipeline import ContextBuilder
from embedder import Embedder

logger = logging.getLogger(__name__)

# --- Request/Response models ---

class BuildContextRequest(BaseModel):
    target_agent: str = Field(..., description="Agent identifier (A1-A10)")
    req_id: str = Field(default="", description="Request ID")
    task_id: str = Field(default="", description="Task ID")
    max_tokens: int = Field(default=8000, description="Token budget ceiling")
    query_text: str = Field(default="", description="Optional free-text query")

class BuildContextResponse(BaseModel):
    success: bool = True
    context_package: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "context-builder"


# --- App Factory ---

def create_app(db_config: dict, embedder: Embedder) -> FastAPI:
    """Create a FastAPI app with the ContextBuilder pipeline wired in."""

    app = FastAPI(
        title="Context Builder",
        description="Intelligent context assembly pipeline for AI-native agents",
        version="0.1.0",
    )

    builder = ContextBuilder(db_config=db_config, embedder=embedder)

    @app.on_event("shutdown")
    def shutdown():
        builder.close()

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse()

    @app.post("/context/build", response_model=BuildContextResponse)
    async def build_context(req: BuildContextRequest):
        """Build a context package for the given agent/task.

        Pipeline: Sanitize -> Select -> Order -> Compress -> Isolate -> Return
        """
        try:
            context_package = builder.build_context(
                target_agent=req.target_agent,
                req_id=req.req_id,
                task_id=req.task_id,
                max_tokens=req.max_tokens,
                query_text=req.query_text,
            )
            return BuildContextResponse(
                success=True,
                context_package=context_package,
            )
        except Exception as e:
            logger.exception("Context build failed")
            raise HTTPException(status_code=500, detail=str(e))

    return app


# --- Default app instance ---

# Use the same DB config as the rest of the ai-native stack
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'ai_native',
    'user': 'ai_native',
    'password': 'ai_native_dev',
}

_default_embedder = Embedder(dim=1024)
app = create_app(db_config=DB_CONFIG, embedder=_default_embedder)


# --- CLI entry point ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("routes:app", host="0.0.0.0", port=8300, reload=True)

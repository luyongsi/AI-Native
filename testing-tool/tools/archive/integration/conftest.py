"""Pytest configuration for Phase 6 E2E integration tests."""

import asyncio
import logging
import os
from typing import Generator

import pytest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def nats_url() -> str:
    """Get NATS URL from environment or use default."""
    return os.getenv("NATS_URL", "nats://localhost:4222")


@pytest.fixture(scope="session")
def db_url() -> str:
    """Get database URL from environment or use default."""
    return os.getenv("DB_URL", "postgresql://localhost:5432/ai_native")


@pytest.fixture(scope="session")
def redis_url() -> str:
    """Get Redis URL from environment or use default."""
    return os.getenv("REDIS_URL", "redis://localhost:6379")


@pytest.fixture(autouse=True)
def setup_logging():
    """Set up logging for each test."""
    logger.info("=" * 80)
    logger.info("Test setup complete")
    yield
    logger.info("Test teardown complete")
    logger.info("=" * 80)


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers",
        "timeout: mark test with timeout in seconds"
    )
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers."""
    for item in items:
        # Add integration marker to all tests in this directory
        item.add_marker(pytest.mark.integration)

        # Add asyncio marker to async tests
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)


@pytest.fixture
def mock_requirement_data():
    """Fixture providing mock requirement data."""
    return {
        "simple": {
            "title": "User Email Verification Field",
            "description": "Add email_verified field to users table",
            "priority": "P2",
        },
        "medium": {
            "title": "User Authentication System",
            "description": "Implement user login functionality",
            "priority": "P1",
        },
        "complex": {
            "title": "Role-Based Access Control",
            "description": "Implement multi-tenant permission management",
            "priority": "P0",
        },
    }


@pytest.fixture
def expected_event_sequence():
    """Fixture providing expected event sequences."""
    return {
        "simple": [
            "requirement.intake",
            "knowledge.analyzed",
            "spec.api_schema_ready",
            "spec.erd_ready",
            "code.generated",
            "test.executed",
        ],
        "medium": [
            "requirement.intake",
            "knowledge.analyzed",
            "spec.api_schema_ready",
            "spec.erd_ready",
            "architecture.dag_built",
            "code.generated",
            "test.executed",
        ],
        "complex": [
            "requirement.intake",
            "knowledge.analyzed",
            "spec.api_schema_ready",
            "spec.erd_ready",
            "architecture.dag_built",
            "code.generated",
            "test.generated",
            "test.executed",
        ],
    }


@pytest.fixture
def quality_thresholds():
    """Fixture providing quality acceptance thresholds."""
    return {
        "simple": {
            "timeout": 7200,  # 2 hours
            "api_schema": True,
            "erd": True,
            "code_quality": 4.0,
            "test_pass_rate": 0.8,
            "test_coverage": 0.6,
        },
        "medium": {
            "timeout": 28800,  # 8 hours
            "api_schema": True,
            "erd": True,
            "dag": True,
            "code_quality": 4.0,
            "test_pass_rate": 0.8,
            "test_coverage": 0.7,
        },
        "complex": {
            "timeout": None,  # No specific timeout
            "complete": True,  # Process should complete
            "min_events": 5,
        },
    }

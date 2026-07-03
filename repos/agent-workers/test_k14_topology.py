"""
Test suite for K14 DependencyTopology (Neo4j integration)

Tests topology building from API schema + ERD and dependency querying.
Requires Neo4j to be running and accessible.
"""

import asyncio
import pytest
from k14.dependency_topology import DependencyTopology

# Test configuration
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "ai-native-2026"


class TestDependencyTopology:
    """Test cases for K14 DependencyTopology."""

    @pytest.fixture
    async def topology(self):
        """Create topology instance."""
        topo = DependencyTopology(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        yield topo
        await topo.close()

    @pytest.fixture
    def sample_api_schema(self):
        """Sample OpenAPI schema for testing."""
        return {
            "paths": {
                "/api/users": {
                    "get": {
                        "summary": "List all users",
                        "description": "Retrieve a list of all users"
                    },
                    "post": {
                        "summary": "Create user",
                        "description": "Create a new user"
                    }
                },
                "/api/users/{id}": {
                    "get": {
                        "summary": "Get user",
                        "description": "Retrieve a specific user by ID"
                    },
                    "put": {
                        "summary": "Update user",
                        "description": "Update a user"
                    }
                },
                "/api/posts": {
                    "get": {
                        "summary": "List posts",
                        "description": "Retrieve all posts"
                    }
                }
            }
        }

    @pytest.fixture
    def sample_erd(self):
        """Sample Entity-Relationship Diagram for testing."""
        return {
            "entities": [
                {
                    "name": "users",
                    "type": "table",
                    "schema": "public",
                    "description": "User accounts"
                },
                {
                    "name": "posts",
                    "type": "table",
                    "schema": "public",
                    "description": "Blog posts"
                },
                {
                    "name": "comments",
                    "type": "table",
                    "schema": "public",
                    "description": "Post comments"
                }
            ],
            "relationships": [
                {
                    "from": "posts",
                    "to": "users",
                    "type": "foreign_key"
                },
                {
                    "from": "comments",
                    "to": "posts",
                    "type": "foreign_key"
                },
                {
                    "from": "comments",
                    "to": "users",
                    "type": "foreign_key"
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_build_topology(self, topology, sample_api_schema, sample_erd):
        """Test building a complete topology."""
        req_id = "req-test-001"

        result = await topology.build_topology(
            req_id=req_id,
            api_schema=sample_api_schema,
            erd=sample_erd,
            requirement_context={
                "title": "User Management System",
                "description": "API for managing users and posts",
                "complexity": "medium"
            }
        )

        assert result["status"] == "completed"
        assert result["req_id"] == req_id
        assert result["nodes_created"] > 0
        assert result["edges_created"] > 0

    @pytest.mark.asyncio
    async def test_query_full_graph(self, topology, sample_api_schema, sample_erd):
        """Test querying the full graph for a requirement."""
        req_id = "req-test-002"

        # Build topology first
        await topology.build_topology(
            req_id=req_id,
            api_schema=sample_api_schema,
            erd=sample_erd
        )

        # Query the graph
        graph = await topology.query_full_graph(req_id, depth=3)

        assert graph["req_id"] == req_id
        assert "requirement" in graph
        assert "nodes" in graph
        assert "edges" in graph
        assert "summary" in graph
        assert graph["summary"]["total_nodes"] > 0
        assert graph["summary"]["total_edges"] > 0

    @pytest.mark.asyncio
    async def test_query_dependencies(self, topology, sample_api_schema, sample_erd):
        """Test querying dependencies for an entity."""
        req_id = "req-test-003"

        # Build topology
        await topology.build_topology(
            req_id=req_id,
            api_schema=sample_api_schema,
            erd=sample_erd
        )

        # Query dependencies for a table
        paths = await topology.query_dependencies("users", depth=2)

        # Should find dependency paths
        assert isinstance(paths, list)

    @pytest.mark.asyncio
    async def test_empty_api_schema(self, topology, sample_erd):
        """Test building topology with empty API schema."""
        req_id = "req-test-004"

        result = await topology.build_topology(
            req_id=req_id,
            api_schema={"paths": {}},
            erd=sample_erd
        )

        assert result["status"] == "completed"
        # Should still have database nodes from ERD
        assert result["nodes_created"] > 0

    @pytest.mark.asyncio
    async def test_empty_erd(self, topology, sample_api_schema):
        """Test building topology with empty ERD."""
        req_id = "req-test-005"

        result = await topology.build_topology(
            req_id=req_id,
            api_schema=sample_api_schema,
            erd={"entities": [], "relationships": []}
        )

        assert result["status"] == "completed"
        # Should still have API endpoint nodes
        assert result["nodes_created"] > 0


# Standalone test runner
async def run_tests():
    """Run tests manually if pytest is not available."""
    print("Running K14 DependencyTopology tests...")
    test = TestDependencyTopology()

    # Create topology
    topology = DependencyTopology(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

    try:
        # Test 1: Build topology
        print("Test 1: Building topology...")
        api_schema = {
            "paths": {
                "/api/users": {"get": {"summary": "List users"}},
                "/api/posts": {"get": {"summary": "List posts"}}
            }
        }
        erd = {
            "entities": [
                {"name": "users", "type": "table"},
                {"name": "posts", "type": "table"}
            ],
            "relationships": [
                {"from": "posts", "to": "users", "type": "foreign_key"}
            ]
        }

        result = await topology.build_topology(
            "req-manual-001",
            api_schema,
            erd,
            {"title": "Test Requirement"}
        )
        print(f"✓ Build result: {result}")

        # Test 2: Query full graph
        print("\nTest 2: Querying full graph...")
        graph = await topology.query_full_graph("req-manual-001", depth=3)
        print(f"✓ Graph summary: {graph.get('summary')}")

        # Test 3: Query dependencies
        print("\nTest 3: Querying dependencies...")
        paths = await topology.query_dependencies("users", depth=2)
        print(f"✓ Found {len(paths)} dependency paths")

        print("\n✓ All tests passed!")

    finally:
        await topology.close()


if __name__ == "__main__":
    asyncio.run(run_tests())

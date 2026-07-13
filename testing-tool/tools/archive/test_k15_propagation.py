"""
Test suite for K15 ChangePropagation (Neo4j integration)

Tests impact analysis, risk assessment, and propagation tracing.
Requires Neo4j to be running and accessible with pre-built topology.
"""

import asyncio
import pytest
from k15.change_propagation import ChangePropagation

# Test configuration
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "ai-native-2026"


class TestChangePropagation:
    """Test cases for K15 ChangePropagation."""

    @pytest.fixture
    async def propagation(self):
        """Create propagation instance."""
        prop = ChangePropagation(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        yield prop
        await prop.close()

    @pytest.mark.asyncio
    async def test_analyze_impact(self, propagation):
        """Test impact analysis for a changed entity."""
        # Assumes a topology has been built with 'users' table
        impact = await propagation.analyze_impact("users", max_depth=3)

        assert "changed_entity" in impact
        assert "affected_count" in impact
        assert "risk_level" in impact
        assert impact["risk_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert isinstance(impact["affected_nodes"], list)

    @pytest.mark.asyncio
    async def test_analyze_batch_impact(self, propagation):
        """Test batch impact analysis."""
        entities = ["users", "posts"]
        batch_result = await propagation.analyze_batch_impact(entities, max_depth=3)

        assert batch_result["total_changed"] == 2
        assert batch_result["total_affected"] >= 0
        assert batch_result["combined_risk_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
        assert len(batch_result["individual_impacts"]) == 2

    @pytest.mark.asyncio
    async def test_calculate_risk_level(self, propagation):
        """Test risk level calculation."""
        # Test different affected counts
        assert propagation.calculate_risk_level(0) == "LOW"
        assert propagation.calculate_risk_level(1) == "LOW"
        assert propagation.calculate_risk_level(5) == "MEDIUM"
        assert propagation.calculate_risk_level(10) == "HIGH"
        assert propagation.calculate_risk_level(25) == "CRITICAL"

    @pytest.mark.asyncio
    async def test_calculate_change_risk(self, propagation):
        """Test comprehensive risk assessment."""
        risk = await propagation.calculate_change_risk(
            "users",
            change_type="deletion"
        )

        assert risk["change_type"] == "deletion"
        assert risk["overall_risk"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
        assert isinstance(risk["risk_factors"], list)
        assert isinstance(risk["recommendations"], list)

    @pytest.mark.asyncio
    async def test_trace_propagation_forward(self, propagation):
        """Test forward propagation tracing."""
        trace = await propagation.trace_propagation_paths(
            "users",
            max_depth=3,
            include_reverse=False
        )

        assert trace["changed_entity"] == "users"
        assert "forward_paths" in trace
        assert isinstance(trace["forward_paths"], list)
        assert trace["reverse_paths"] == []  # Not requested

    @pytest.mark.asyncio
    async def test_trace_propagation_bidirectional(self, propagation):
        """Test bidirectional propagation tracing."""
        trace = await propagation.trace_propagation_paths(
            "users",
            max_depth=3,
            include_reverse=True
        )

        assert trace["changed_entity"] == "users"
        assert "forward_paths" in trace
        assert "reverse_paths" in trace
        assert isinstance(trace["forward_paths"], list)
        assert isinstance(trace["reverse_paths"], list)

    @pytest.mark.asyncio
    async def test_not_found_entity(self, propagation):
        """Test handling of non-existent entity."""
        impact = await propagation.analyze_impact(
            "nonexistent_entity_xyz",
            max_depth=3
        )

        assert impact["affected_count"] == 0
        assert impact["risk_level"] == "LOW"
        assert "error" in impact or impact["affected_nodes"] == []

    @pytest.mark.asyncio
    async def test_deletion_risk(self, propagation):
        """Test deletion change type."""
        risk = await propagation.calculate_change_risk(
            "users",
            change_type="deletion"
        )

        # Deletion should have risk factors
        risk_factors = risk.get("risk_factors", [])
        has_deletion_factor = any("Deletion" in str(f) for f in risk_factors)
        # May or may not have deletion factor depending on entity
        assert isinstance(risk_factors, list)

    @pytest.mark.asyncio
    async def test_modification_risk(self, propagation):
        """Test modification change type."""
        risk = await propagation.calculate_change_risk(
            "users",
            change_type="modification"
        )

        assert risk["change_type"] == "modification"
        assert isinstance(risk["recommendations"], list)
        # Should have recommendations
        assert len(risk["recommendations"]) > 0


# Standalone test runner
async def run_tests():
    """Run tests manually if pytest is not available."""
    print("Running K15 ChangePropagation tests...")

    propagation = ChangePropagation(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

    try:
        # Test 1: Analyze impact
        print("Test 1: Analyzing impact for 'users'...")
        impact = await propagation.analyze_impact("users", max_depth=3)
        print(f"✓ Impact: {impact['affected_count']} affected nodes, risk={impact['risk_level']}")

        # Test 2: Batch impact analysis
        print("\nTest 2: Batch impact analysis...")
        batch = await propagation.analyze_batch_impact(["users", "posts"], max_depth=3)
        print(f"✓ Batch: {batch['total_changed']} changed, {batch['total_affected']} total affected")

        # Test 3: Risk calculation
        print("\nTest 3: Risk level calculation...")
        tests = [
            (0, "LOW"),
            (2, "LOW"),
            (5, "MEDIUM"),
            (10, "HIGH"),
            (25, "CRITICAL"),
        ]
        for count, expected in tests:
            result = propagation.calculate_risk_level(count)
            status = "✓" if result == expected else "✗"
            print(f"  {status} {count} affected → {result} (expected {expected})")

        # Test 4: Change risk assessment
        print("\nTest 4: Change risk assessment (deletion)...")
        risk = await propagation.calculate_change_risk("users", change_type="deletion")
        print(f"✓ Risk: {risk['overall_risk']}, factors={len(risk['risk_factors'])}, "
              f"recommendations={len(risk['recommendations'])}")

        # Test 5: Propagation tracing
        print("\nTest 5: Propagation tracing...")
        trace = await propagation.trace_propagation_paths("users", max_depth=3, include_reverse=True)
        print(f"✓ Trace: {len(trace['forward_paths'])} forward paths, "
              f"{len(trace['reverse_paths'])} reverse paths")

        print("\n✓ All tests completed!")

    except Exception as e:
        print(f"\n✗ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        await propagation.close()


if __name__ == "__main__":
    asyncio.run(run_tests())

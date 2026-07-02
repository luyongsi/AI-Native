"""Agent-specific ranking strategies for context ordering."""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentStrategy:
    """Agent-specific content type boosting strategies.

    Different agents prioritize different content types:
    - A4 (Spec Writer): API schemas, ERDs, specifications
    - A6 (Architect): Architecture docs, ERDs, diagrams
    - A9 (Dev Agent): Code, tests, implementations
    - A10 (QA Agent): Tests, specs, docs
    """

    # Content type boost multipliers per agent
    STRATEGIES = {
        "A4": {
            # Spec Writer: prioritize structured content
            "api_schema": 1.5,
            "erd": 1.5,
            "spec": 1.2,
            "diagram": 1.1,
            "doc": 1.0,
            "knowledge": 0.9,
            "code": 0.7,
            "test": 0.6,
        },
        "A6": {
            # Architect: prioritize architecture & design docs
            "architecture": 1.5,
            "erd": 1.3,
            "diagram": 1.2,
            "api_schema": 1.1,
            "doc": 1.0,
            "knowledge": 0.9,
            "code": 0.7,
            "test": 0.5,
        },
        "A9": {
            # Dev Agent: prioritize code & implementation
            "code": 1.5,
            "test": 1.3,
            "implementation": 1.2,
            "knowledge": 1.0,
            "doc": 0.8,
            "api_schema": 0.8,
            "erd": 0.6,
            "diagram": 0.5,
            "architecture": 0.5,
        },
        "A10": {
            # QA Agent: prioritize tests & specs
            "test": 1.5,
            "spec": 1.3,
            "doc": 1.1,
            "knowledge": 1.0,
            "code": 0.8,
            "api_schema": 0.8,
            "erd": 0.6,
            "architecture": 0.5,
        },
        "default": {
            # Default: no specific boosting
        },
    }

    # Context window limits per agent
    CONTEXT_LIMITS = {
        "A4": 100000,    # Spec Writer
        "A6": 150000,    # Architect (needs more context)
        "A9": 200000,    # Dev Agent (needs most code context)
        "A10": 100000,   # QA Agent
        "default": 100000,
    }

    @staticmethod
    def get_strategy(agent_id: str) -> Dict[str, float]:
        """Get content type boosts for an agent.

        Args:
            agent_id: Agent identifier (A1-A10)

        Returns:
            Dictionary mapping content_type -> boost multiplier
        """
        return AgentStrategy.STRATEGIES.get(agent_id, AgentStrategy.STRATEGIES["default"])

    @staticmethod
    def get_context_limit(agent_id: str) -> int:
        """Get context window limit for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Max tokens for context
        """
        return AgentStrategy.CONTEXT_LIMITS.get(agent_id, AgentStrategy.CONTEXT_LIMITS["default"])

    @staticmethod
    def adjust_scores(candidates: List[Dict], agent_id: str) -> List[Dict]:
        """Apply agent-specific score adjustments.

        Args:
            candidates: List of candidate dicts with 'relevance_score' and 'content_type'
            agent_id: Target agent ID

        Returns:
            Same list with adjusted relevance_score values
        """
        strategy = AgentStrategy.get_strategy(agent_id)

        if not strategy:
            # No specific strategy, return unchanged
            return candidates

        adjusted_count = 0
        for candidate in candidates:
            if 'relevance_score' not in candidate:
                continue

            content_type = candidate.get('content_type', '')
            boost = strategy.get(content_type, 1.0)

            original_score = candidate['relevance_score']
            candidate['relevance_score'] = min(1.0, original_score * boost)

            if boost != 1.0:
                adjusted_count += 1

        if adjusted_count > 0:
            logger.debug(
                f"Adjusted {adjusted_count} candidate scores for agent {agent_id}"
            )

        return candidates

    @staticmethod
    def should_prioritize_content_type(agent_id: str, content_type: str) -> bool:
        """Check if a content type is prioritized for an agent.

        Args:
            agent_id: Target agent ID
            content_type: Content type to check

        Returns:
            True if boost > 1.0
        """
        strategy = AgentStrategy.get_strategy(agent_id)
        boost = strategy.get(content_type, 1.0)
        return boost > 1.0

    @staticmethod
    def get_agent_info(agent_id: str) -> Dict:
        """Get comprehensive agent strategy info.

        Args:
            agent_id: Agent identifier

        Returns:
            Dictionary with strategy, context_limit, and description
        """
        agent_descriptions = {
            "A4": "Spec Writer - API specifications and documentation",
            "A6": "Architect - System design and architecture",
            "A9": "Dev Agent - Code implementation and debugging",
            "A10": "QA Agent - Test cases and quality assurance",
        }

        return {
            'agent_id': agent_id,
            'description': agent_descriptions.get(agent_id, "Unknown agent"),
            'strategy': AgentStrategy.get_strategy(agent_id),
            'context_limit': AgentStrategy.get_context_limit(agent_id),
        }

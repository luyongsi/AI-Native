"""
A1 Agent — Requirement Analysis Agent

Sub-modules:
  - agent: A1Agent main class — orchestrate MCP + LLM + BDD + wireframe
  - analyzer: DraftBuilder (LLM streaming), ClarificationEngine, MCPClient
  - wireframe: WireframeGenerator (LLM-driven low-fidelity wireframes)
  - bdd: BDDDrafter (GWT acceptance criteria generation)
  - sources: External data source integrations (Feishu chat, meeting, docs)
  - dialog: Multi-round clarification state machine
  - bot: Feishu bot integration for card-based interaction
"""
from .agent import A1Agent

__all__ = ["A1Agent"]

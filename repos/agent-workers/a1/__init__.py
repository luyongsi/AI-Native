"""
A1 Sub-Modules — Requirement Intake Agent

Sub-modules:
  - nlp: Natural language intent extraction from user messages
  - wireframe: Low-fidelity wireframe generation from requirements
  - bdd: GWT (Given-When-Then) scenario drafting
  - sources: External data source integrations (Feishu chat, meeting, docs)
  - dialog: Multi-round clarification state machine
  - bot: Feishu bot integration for card-based interaction
"""

import logging

logger = logging.getLogger(__name__)

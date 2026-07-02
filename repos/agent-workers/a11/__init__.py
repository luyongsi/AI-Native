"""
A11 VisAgent Integration Package

Provides the bridge between the AI-Native Development Platform's A11 test agent
and the external VisAgent visual testing service.

Modules:
    tester             — VisAgentTester for executing visual test cases
    tester_fallback    — Playwright fallback when VisAgent is unavailable
    healer_client      — VisAgent self-healing client
    visagent_event_handler — NATS event handler for VisAgent lifecycle events
    result_converter   — Bidirectional format conversion between VisAgent and AI Agent
    stryker_runner     — Stryker mutation testing runner
    stryker_config_template — Stryker configuration template (JSON)
    mutation_reporter  — Mutation testing report generation
"""

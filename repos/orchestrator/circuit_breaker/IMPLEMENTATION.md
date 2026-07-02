"""Circuit Breaker Strategy Upgrade (Task #43) - Implementation Guide

This document describes the complete circuit breaker escalation system that
automatically upgrades agent retry strategies through:
  1. Few-shot example injection
  2. Strong model switching
  3. Human escalation via Feishu notifications
"""

# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

"""
When an agent fails, the circuit breaker automatically escalates through three
levels of increasing intervention:

  Level 1: FEW_SHOT (1st failure)
    → Injects task-specific few-shot examples to improve agent guidance
    → Uses original model (DeepSeek v3)

  Level 2: STRONG_MODEL (2nd failure)
    → Switches to Claude 3.5 Sonnet (higher reasoning capability)
    → Maintains few-shot examples
    → Lower temperature (0.2) for more deterministic behavior

  Level 3: HUMAN (3rd failure)
    → Sends Feishu webhook notification to ops team
    → Attempts one final time with Claude Opus (highest capability)
    → After this, escalation is exhausted and task fails

Successful execution at any level resets the circuit breaker to NORMAL.
"""

# ══════════════════════════════════════════════════════════════════════════════
# MODULE STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

"""
repos/orchestrator/circuit_breaker/
├── circuit_breaker.py          # Core escalation tracking
├── few_shot_examples.py        # Task-specific examples for injection
├── model_selector.py           # Model tier selection
├── human_escalation.py         # Feishu webhook notifications
├── metrics.py                  # Prometheus-ready metrics
├── agent_invoker.py            # Main orchestration logic
├── test_circuit_breaker.py     # Comprehensive test suite
└── __init__.py                 # Public exports
"""

# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

"""
from circuit_breaker import get_agent_invoker

invoker = get_agent_invoker()

# Define your agent function
async def my_agent(req_id: str, agent_id: str, context: dict) -> dict:
    # Agent implementation
    return {"result": "..."}

# Invoke with automatic escalation
try:
    result = await invoker.invoke_with_escalation(
        agent_func=my_agent,
        req_id="req-12345",
        agent_id="A9",
        context={"task": "generate_code"},
        task_type="code_generation"
    )
except Exception as e:
    logger.error(f"Agent failed after all escalations: {e}")
"""

# ══════════════════════════════════════════════════════════════════════════════
# COMPONENT DETAILS
# ══════════════════════════════════════════════════════════════════════════════

"""
1. CIRCUIT BREAKER (circuit_breaker.py)
   ─────────────────────────────────────

   Tracks per-(req_id, agent_id) failure counts and escalation levels.

   Key Classes:
   - EscalationLevel: Enum with NORMAL, FEW_SHOT, STRONG_MODEL, HUMAN
   - FailureRecord: Tracks failures for a single (req_id, agent_id)
   - CircuitBreaker: Main state management

   Key Methods:
   - get_level(req_id, agent_id) → EscalationLevel
       Returns current escalation level for an agent
   - record_failure(req_id, agent_id) → EscalationLevel
       Increments failure count and returns new level
   - reset(req_id, agent_id)
       Clears state on successful execution
   - cleanup(req_id)
       Removes all states for a requirement

   Usage:
   ```
   from circuit_breaker import get_circuit_breaker

   cb = get_circuit_breaker()
   level = cb.get_level("req-1", "A4")  # EscalationLevel.NORMAL
   new_level = cb.record_failure("req-1", "A4")  # EscalationLevel.FEW_SHOT
   cb.reset("req-1", "A4")  # Back to NORMAL
   ```

   Implementation Notes:
   - Thread-safe dict-based state store
   - Follows escalation order: NORMAL → FEW_SHOT → STRONG_MODEL → HUMAN
   - Module-level singleton accessed via get_circuit_breaker()


2. FEW-SHOT EXAMPLES (few_shot_examples.py)
   ──────────────────────────────────────────

   Provides task-specific examples for each agent type.

   Example Library Structure:
   FEW_SHOT_EXAMPLES = {
       "A4": {
           "api_schema": [
               {
                   "requirement": "User login endpoint",
                   "context": "REST API",
                   "output": {"endpoint": "/auth/login", ...}
               },
               ...
           ]
       },
       "A9": {
           "code_generation": [
               {
                   "requirement": "User registration",
                   "language": "python",
                   "output": "async def register_user(...)..."
               },
               ...
           ]
       }
   }

   Key Functions:
   - get_few_shot_examples(agent_id, task_type=None, count=3) → list
       Retrieves up to *count* examples for an agent/task combo
   - inject_few_shot_into_context(context, agent_id, task_type=None) → dict
       Injects examples into execution context

   Usage:
   ```
   from circuit_breaker import inject_few_shot_into_context

   context = {"task": "design_api"}
   context = inject_few_shot_into_context(context, "A4", "api_schema")
   # context now has "few_shot_examples" key with 3 examples
   ```

   Extensibility:
   Add new agents/tasks to FEW_SHOT_EXAMPLES dict and the system
   automatically uses them. Each example should have:
   - requirement: What the example demonstrates
   - context: Use case or domain context
   - output: The actual output/code to inject


3. MODEL SELECTOR (model_selector.py)
   ───────────────────────────────────

   Manages model tier selection and switching logic.

   Model Hierarchy:
   ┌─────────────────────────────────────────────┐
   │ Tier    │ Provider   │ Model              │ Temp │
   ├─────────────────────────────────────────────┤
   │ NORMAL  │ DeepSeek   │ deepseek-v3        │ 0.3  │
   │ STRONG  │ Anthropic  │ claude-3-5-sonnet  │ 0.2  │
   │ ULTRA   │ Anthropic  │ claude-opus-4-7    │ 0.1  │
   └─────────────────────────────────────────────┘

   Key Classes:
   - ModelTier: Enum with NORMAL, STRONG, ULTRA
   - ModelSelector: Selects and tracks model changes

   Key Methods:
   - select_model_by_tier(tier: ModelTier) → dict
       Returns full model config for a tier
   - select_model_for_escalation(failure_count: int) → dict
       Maps failure count to tier and returns config
   - record_switch(from_model, to_model)
       Records model switch for metrics

   Usage:
   ```
   from circuit_breaker import override_model_in_context

   context = {}
   context = override_model_in_context(context, failure_count=1)
   # context["model_config"] now has claude-3-5-sonnet settings
   ```

   Cost Considerations:
   - DeepSeek v3: Cheapest, good for standard tasks
   - Claude Sonnet: ~10x cost, 2nd generation models
   - Claude Opus: ~20x cost, highest quality, use as last resort


4. HUMAN ESCALATION (human_escalation.py)
   ──────────────────────────────────────

   Sends interactive Feishu cards to notify operations team.

   Configuration:
   Set FEISHU_WEBHOOK_URL environment variable:
   ```bash
   export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."
   ```

   Card Format:
   - Red header with emoji alert icon
   - Requirement ID and Agent name
   - Formatted error message
   - Action buttons to view details and logs
   - Timestamp in ISO format

   Key Classes:
   - HumanEscalation: Manages webhook notifications

   Key Methods:
   - request_human_help(req_id, agent_id, error_message, context_summary)
       Sends Feishu notification, returns True/False
   - _build_card(...) → dict
       Constructs Feishu interactive card payload

   Usage:
   ```
   from circuit_breaker import escalate_to_human

   await escalate_to_human(
       req_id="req-12345",
       agent_id="A9",
       error_message="Failed to generate code",
       context_summary="Python backend service"
   )
   ```

   Testing:
   To validate webhook format without sending:
   ```python
   escalation = HumanEscalation()
   card = escalation.build_test_card()
   print(json.dumps(card, indent=2))
   ```

   Implementation Notes:
   - Gracefully handles missing webhook URL (logs warning, continues)
   - Card is async-ready but currently logs instead of posting
   - Production deployment needs httpx or aiohttp integration


5. METRICS (metrics.py)
   ─────────────────────

   Collects and exports monitoring data for circuit breaker.

   Key Metrics:
   - escalations_total: Counter by (agent_id, level)
       Tracks how many times each escalation level was triggered
   - human_requests_total: Counter by agent_id
       Tracks how many human escalations per agent
   - model_switches_total: Counter by (from_model, to_model)
       Tracks model upgrade patterns
   - current_failures: Gauge by (req_id, agent_id)
       Current failure count for tracking

   Key Class:
   - CircuitBreakerMetrics: In-memory metrics store

   Key Methods:
   - increment_escalation(agent_id, level)
   - increment_human_request(agent_id)
   - increment_model_switch(from_model, to_model)
   - set_failure_count(req_id, agent_id, count)
   - get_*_count(...) with optional filtering
   - to_dict() → dict
       Export all metrics
   - reset()
       Clear all (useful for testing)

   Usage:
   ```
   from circuit_breaker import get_metrics

   metrics = get_metrics()
   metrics.increment_escalation("A9", "FEW_SHOT")
   metrics.increment_human_request("A9")

   # Export for monitoring
   data = metrics.to_dict()
   # {
   #     "escalations_total": {("A9", "FEW_SHOT"): 1, ...},
   #     "human_requests_total": {"A9": 1},
   #     ...
   # }
   ```

   Prometheus Integration:
   These metrics are designed for easy export to Prometheus.
   Future work: Add prometheus-client instrumentation.


6. AGENT INVOKER (agent_invoker.py)
   ─────────────────────────────────

   High-level orchestration that ties all components together.

   Key Classes:
   - AgentInvoker: Main orchestration engine

   Key Methods:
   - invoke_with_escalation(agent_func, req_id, agent_id, context, task_type=None)
       Main entry point for executing agents with automatic escalation

   Invocation Flow:
   1. Check current escalation level for (req_id, agent_id)
   2. Apply escalation strategy:
      - FEW_SHOT: Inject examples
      - STRONG_MODEL: Override model config
      - HUMAN: Send Feishu + use ultra model
   3. Execute agent function
   4. On success: Reset circuit breaker
   5. On failure: Record failure and escalate (if retries remain)
   6. After max_retries: Raise exception

   Usage:
   ```
   from circuit_breaker import get_agent_invoker

   invoker = get_agent_invoker()

   async def my_agent(req_id, agent_id, context):
       # Implementation
       return {"result": "..."}

   result = await invoker.invoke_with_escalation(
       agent_func=my_agent,
       req_id="req-12345",
       agent_id="A9",
       context={"task": "generate_code"},
       task_type="code_generation"
   )
   ```

   Configuration:
   - max_retries: Default 3 (NORMAL → FEW_SHOT → STRONG_MODEL → HUMAN)

   Implementation Notes:
   - Full context dict is copied before each attempt
   - Metrics are recorded at each escalation level
   - Failure count is tracked and exposed via metrics
   - Module-level singleton via get_agent_invoker()
"""

# ══════════════════════════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════════════════════════

"""
Run the test suite:

    cd repos/orchestrator/circuit_breaker
    python -m pytest test_circuit_breaker.py -v

Test Coverage:
- CircuitBreaker: Escalation progression, reset, independence, cleanup
- FewShotExamples: Example retrieval, context injection, count limits
- ModelSelector: Model tier selection, escalation mapping
- HumanEscalation: Card structure, agent names, buttons, error handling
- Metrics: Counters, gauges, filtering, export
- AgentInvoker: Successful invocation, escalation on failure, exhaustion
- Integration: Full flow from few-shot to human

Example Test Run:
    >>> pytest test_circuit_breaker.py::TestCircuitBreaker::test_escalation_progression -v
    >>> pytest test_circuit_breaker.py::TestAgentInvoker -v
    >>> pytest test_circuit_breaker.py::TestIntegration -v
"""

# ══════════════════════════════════════════════════════════════════════════════
# MONITORING & OBSERVABILITY
# ══════════════════════════════════════════════════════════════════════════════

"""
Key Metrics to Monitor:

1. Escalation Rate
   circuit_breaker_escalations_total{agent_id, level}
   
   Track which agents/levels are escalating most frequently.
   High escalation suggests agents may need tuning.

2. Human Escalation Rate
   circuit_breaker_human_requests_total{agent_id}
   
   Critical metric — indicates tasks requiring manual intervention.
   Should be < 1% of total tasks.

3. Model Upgrade Cost
   model_switches_total{from_model, to_model}
   
   Each upgrade costs more. Track trends to identify problem agents.
   Cost: deepseek-v3 < sonnet (~10x) < opus (~20x)

4. Success After Escalation
   Success rate per escalation level
   
   Calculate from task completion metrics:
   - Few-shot success rate
   - Strong model success rate
   - Human escalation final outcome

5. Escalation Latency
   Time spent in each escalation level
   
   Few-shot should be fast (example injection).
   Model switch adds some latency.
   Human escalation blocks until manual intervention.

Sample Monitoring Query (Prometheus):
    increase(circuit_breaker_escalations_total[5m]) by (agent_id, level)
    
This shows escalation rate per agent over 5 minutes.
"""

# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION WITH ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

"""
To integrate with existing orchestrator activities:

1. Import in activities/dispatch_agent.py:
   from circuit_breaker import get_agent_invoker

2. Wrap agent invocation:
   invoker = get_agent_invoker()
   result = await invoker.invoke_with_escalation(
       agent_func=agent_execute,
       req_id=req_id,
       agent_id=agent_type,
       context=context,
       task_type=determine_task_type(context)
   )

3. Handle exhaustion:
   try:
       result = await invoker.invoke_with_escalation(...)
   except Exception as e:
       logger.error(f"Agent failed after all escalations: {e}")
       # Publish failure event to NATS
       await nats.publish("orchestrator.agent_failed", {...})

4. Clean up on requirement completion:
   from circuit_breaker import get_circuit_breaker
   cb = get_circuit_breaker()
   cb.cleanup(req_id)  # Free up memory

Example Integration in dispatch_agent.py:

    @activity.defn(name="dispatch_agent_with_escalation")
    async def dispatch_agent_with_escalation(
        req_id: str, state: str, context: str = ""
    ) -> dict:
        # Parse context
        ctx_dict = json.loads(context) if context else {}
        
        # Get agent and task type
        agent_type = map_state_to_agent(state)
        task_type = infer_task_type(agent_type, ctx_dict)
        
        # Create agent function
        async def agent_fn(req_id, agent_id, context):
            # Call actual agent (e.g., via NATS worker)
            return await agent_execute(agent_type, context)
        
        # Invoke with escalation
        invoker = get_agent_invoker()
        try:
            result = await invoker.invoke_with_escalation(
                agent_func=agent_fn,
                req_id=req_id,
                agent_id=agent_type,
                context=ctx_dict,
                task_type=task_type
            )
            return {"ok": True, "result": result}
        except Exception as e:
            logger.error(f"Agent escalation exhausted: {e}")
            return {"ok": False, "error": str(e)}
"""

# ══════════════════════════════════════════════════════════════════════════════
# TROUBLESHOOTING
# ══════════════════════════════════════════════════════════════════════════════

"""
Issue: Agents keep escalating to human
  → Check if few-shot examples are appropriate for the task
  → Verify model override is being applied (check logs)
  → Consider adding more/better examples to FEW_SHOT_EXAMPLES

Issue: Feishu notifications not being sent
  → Verify FEISHU_WEBHOOK_URL environment variable is set
  → Check webhook URL format matches Feishu open API
  → Look for warning logs about webhook_url not configured
  → Test webhook independently: escalation.build_test_card()

Issue: Model switching not working
  → Verify model API keys are configured:
    - DEEPSEEK_API_KEY for normal tier
    - ANTHROPIC_API_KEY for strong/ultra tiers
  → Check model names match current API versions
  → Review agent code to ensure it respects model_config from context

Issue: Metrics not accurate
  → Ensure circuit breaker is not reset prematurely
  → Check metrics.to_dict() output for data integrity
  → Verify get_agent_invoker() is using singleton (not creating new instances)

Issue: Memory leak from circuit breaker state
  → Always call cb.cleanup(req_id) on requirement completion
  → Alternatively, implement TTL-based cleanup for stale entries
  → Monitor _state dict size in production
"""

# ══════════════════════════════════════════════════════════════════════════════
# FUTURE ENHANCEMENTS
# ══════════════════════════════════════════════════════════════════════════════

"""
1. Adaptive Escalation Strategy
   - Learn which escalations work best per agent
   - Adjust few-shot examples based on success rates
   - Skip ineffective levels based on historical data

2. Feishu Webhook Posting
   - Implement actual async HTTP POST with httpx
   - Handle webhook rate limits and retries
   - Add response tracking (did human respond?)

3. Prometheus Exporter
   - Expose metrics via /metrics endpoint
   - Integration with Grafana dashboards
   - Alert on high human escalation rate

4. Configurable Escalation Chains
   - Allow per-agent custom escalation sequences
   - Different max_retries per agent complexity
   - Custom few-shot selections based on error type

5. Error-Aware Escalation
   - Different strategies based on error type
   - E.g., timeout → increase max_tokens, syntax error → inject examples
   - Categorize errors for better decision-making

6. Soft Escalation Circuit Breaker
   - Probabilistic escalation (don't always go to human)
   - Implement exponential backoff between retries
   - Graceful degradation with fallback responses
"""

if __name__ == "__main__":
    print(__doc__)

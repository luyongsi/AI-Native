import asyncio
import sys
import time
sys.path.insert(0, ".")

# Test each agent's init + wrapper installation
agents_to_test = [
    ("a1_requirement_intake", "A1RequirementIntake"),
    ("a2_knowledge_analyst", "A2KnowledgeAnalyst"),
    ("a3_ui_generator", "UIGeneratorAgent"),
    ("a4_spec_writer", "A4SpecWriter"),
    ("a5_design_review", "DesignReviewAgent"),
    ("a6_spec_decomposer", "SpecDecomposerAgent"),
    ("a7_test_case_generator", "TestCaseGeneratorAgent"),
    ("a8_architecture_expert", "ArchitectureExpertAgent"),
    ("a9_dev_agent_stub", "DevAgent"),
    ("a11_test_agent_stub", "A11TestAgentStub"),
    ("a12_code_review", "CodeReviewAgent"),
    ("fast_channel_classifier", "FastChannelClassifier"),
]

import importlib

async def test():
    results = []
    for mod_name, cls_name in agents_to_test:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            agent = cls()
            await agent.init()

            wrapped_methods = []
            for method_name in ("_call_llm", "_mock_llm"):
                if hasattr(agent, method_name):
                    fn = getattr(agent, method_name)
                    wrapped = hasattr(fn, "__wrapped__")
                    wrapped_methods.append(f"{method_name}={wrapped}")

            await agent.close()
            results.append(f"  OK   {cls_name}: init OK, {', '.join(wrapped_methods) if wrapped_methods else 'no LLM method'}")
        except Exception as e:
            results.append(f"  FAIL {cls_name}: {e}")

    print("\n=== Agent Init Results ===")
    for r in results:
        print(r)
asyncio.run(test())

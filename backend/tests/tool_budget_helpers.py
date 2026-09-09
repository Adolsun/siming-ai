"""Model-bound budgets used by native executor fixtures."""
from app.services.conversation_context import (
    GenerationModelBinding,
    RequestTokenComponents,
    Utf8ByteTokenCounter,
    build_request_budget,
)


def request_budget(available: int = 250_000):
    counter = Utf8ByteTokenCounter()
    binding = GenerationModelBinding(
        task_type="assistant", provider="test", model_name="budgeted",
        normalized_model="test:budgeted", protocol="native",
        context_window_tokens=available + 5_512, max_output_tokens=4_000,
        token_counter_id=counter.counter_id, capacity_assurance=counter.assurance,
        prompt_contract_hash="test-prompt", tool_schema_hash="test-tools",
        config_fingerprint="test-config",
    )
    return build_request_budget(
        binding=binding, counter=counter,
        components=RequestTokenComponents(system_prompt_tokens=1_000),
        safety_margin_tokens=512,
    )

"""Provider normalization and pricing tests."""

from __future__ import annotations

from types import SimpleNamespace

from google.genai import types

from app.meta_harness.providers import (
    GoogleGenAIProvider,
    NormalizedContentBlock,
    _google_contents,
    estimate_cost_usd,
    google_retry_delay,
    is_retryable_google_error,
    provider_for_model,
)


def test_provider_is_inferred_from_model_name() -> None:
    assert provider_for_model("claude-haiku-4-5-20251001") == "anthropic"
    assert provider_for_model("gemini-3.7-flash") == "google"


def test_google_message_conversion_preserves_tool_context() -> None:
    signature = b"thought-signature"
    messages = [
        {"role": "user", "content": "inspect"},
        {
            "role": "assistant",
            "content": [
                NormalizedContentBlock(
                    type="tool_use",
                    id="call-1",
                    name="read_file",
                    input={"path": "example.py"},
                    thought_signature=signature,
                )
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "value = 1",
                    "is_error": False,
                }
            ],
        },
    ]

    contents = _google_contents(messages)

    assert [content.role for content in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].function_call.name == "read_file"
    assert contents[1].parts[0].thought_signature == signature
    assert contents[2].parts[0].function_response.name == "read_file"


async def test_google_provider_normalizes_function_calls_and_usage() -> None:
    function_part = types.Part.from_function_call(
        name="task_complete",
        args={},
    )
    function_part.function_call.id = "call-1"
    function_part.thought_signature = b"signature"
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=types.Content(role="model", parts=[function_part]),
                finish_reason="STOP",
            )
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=4,
            thoughts_token_count=3,
            cached_content_token_count=2,
        ),
        model_version="gemini-3.7-flash",
    )

    class FakeModels:
        async def generate_content(self, **kwargs):
            assert kwargs["model"] == "gemini-3.7-flash"
            return response

    provider = GoogleGenAIProvider(api_key="test-key")
    provider.client = SimpleNamespace(aio=SimpleNamespace(models=FakeModels()))
    normalized = await provider.call(
        [{"role": "user", "content": "finish"}],
        [
            {
                "name": "task_complete",
                "description": "finish",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        model="gemini-3.7-flash",
        max_tokens=100,
        system_prompt="system",
        tool_choice=None,
        temperature=0.2,
        seed=42,
    )

    assert normalized.model == "gemini-3.7-flash"
    assert normalized.content[0].name == "task_complete"
    assert normalized.content[0].id == "call-1"
    assert normalized.content[0].thought_signature == b"signature"
    assert normalized.usage.input_tokens == 12
    assert normalized.usage.output_tokens == 7
    assert normalized.usage.cache_read_input_tokens == 2


def test_google_retry_delay_honors_server_hint() -> None:
    error = RuntimeError("Please retry in 58.25s")
    assert google_retry_delay(error, 0) == 59.25


def test_daily_google_quota_is_not_retried() -> None:
    class QuotaError(RuntimeError):
        code = 429

    daily = QuotaError("quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    minute = QuotaError("Please retry in 58s")
    assert is_retryable_google_error(daily) is False
    assert is_retryable_google_error(minute) is True


def test_gemini_cost_estimate_uses_versioned_pricing() -> None:
    estimate = estimate_cost_usd(
        "gemini-3.7-flash",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cached_tokens=0,
    )
    assert estimate == (9.0, "google-gemini-pricing-2026-08-16")
    lite_estimate = estimate_cost_usd(
        "gemini-3.5-flash-lite",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cached_tokens=0,
    )
    assert lite_estimate == (2.8, "google-gemini-pricing-2026-08-16")
    stable_lite_estimate = estimate_cost_usd(
        "gemini-3.1-flash-lite",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cached_tokens=0,
    )
    assert stable_lite_estimate == (
        1.75,
        "google-gemini-pricing-2026-08-16",
    )

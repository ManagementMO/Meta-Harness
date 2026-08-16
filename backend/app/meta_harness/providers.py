"""Provider adapters that normalize model responses for the inner harness."""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class NormalizedContentBlock:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    thought_signature: bytes | None = None


@dataclass
class NormalizedUsage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class NormalizedResponse:
    content: list[NormalizedContentBlock]
    usage: NormalizedUsage
    model: str


class ModelProvider(Protocol):
    name: str
    client: Any

    async def call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        system_prompt: str,
        tool_choice: dict[str, Any] | None,
        temperature: float | None,
        seed: int | None,
    ) -> Any: ...


def provider_for_model(model: str) -> str:
    normalized = model.lower()
    if normalized.startswith(("gemini-", "gemma-")):
        return "google"
    if normalized.startswith("claude-"):
        return "anthropic"
    raise ValueError(f"cannot infer provider for model: {model}")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or export it "
                "before running an Anthropic model."
            )
        self.client = anthropic.AsyncAnthropic(api_key=resolved_key)

    async def call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        system_prompt: str,
        tool_choice: dict[str, Any] | None,
        temperature: float | None,
        seed: int | None,
    ) -> Any:
        del seed
        kwargs: dict[str, Any] = {}
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            kwargs["temperature"] = temperature
        return await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            tools=tools,
            system=system_prompt,
            **kwargs,
        )


def _block_value(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _google_contents(messages: list[dict[str, Any]]) -> list[Any]:
    from google.genai import types

    tool_names: dict[str, str] = {}
    contents: list[Any] = []
    for message in messages:
        content = message.get("content", "")
        blocks = content if isinstance(content, list) else [content]
        parts = []
        contains_function_response = False
        for block in blocks:
            if isinstance(block, str):
                parts.append(types.Part.from_text(text=block))
                continue
            block_type = _block_value(block, "type")
            if block_type == "text":
                parts.append(
                    types.Part.from_text(text=str(_block_value(block, "text", "")))
                )
            elif block_type == "tool_use":
                call_id = str(_block_value(block, "id", ""))
                name = str(_block_value(block, "name", ""))
                tool_names[call_id] = name
                function_part = types.Part.from_function_call(
                    name=name,
                    args=dict(_block_value(block, "input", {}) or {}),
                )
                function_part.thought_signature = _block_value(
                    block,
                    "thought_signature",
                )
                parts.append(function_part)
            elif block_type == "tool_result":
                call_id = str(_block_value(block, "tool_use_id", ""))
                name = tool_names.get(call_id) or str(
                    _block_value(block, "name", "unknown_tool")
                )
                parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={
                            "result": _block_value(block, "content", ""),
                            "is_error": bool(_block_value(block, "is_error", False)),
                        },
                    )
                )
                contains_function_response = True
        if not parts:
            continue
        role = "model" if message.get("role") == "assistant" else "user"
        if contains_function_response:
            role = "user"
        contents.append(types.Content(role=role, parts=parts))
    return contents


def _google_tools(tools: list[dict[str, Any]]) -> list[Any]:
    from google.genai import types

    if not tools:
        return []
    declarations = [
        types.FunctionDeclaration(
            name=str(tool["name"]),
            description=str(tool.get("description", "")),
            parameters_json_schema=tool.get("input_schema") or {
                "type": "object",
                "properties": {},
            },
        )
        for tool in tools
    ]
    return [types.Tool(function_declarations=declarations)]


_GOOGLE_RATE_LOCK = threading.Lock()
_GOOGLE_NEXT_REQUEST_AT: dict[str, float] = {}
_GOOGLE_DEFAULT_INTERVALS = {
    "gemini-3.7-flash": 12.5,
    "gemini-3.6-flash": 12.5,
    "gemini-3.5-flash-lite": 4.1,
    "gemini-3.1-flash-lite": 4.1,
}


def is_retryable_google_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    message = str(exc).lower()
    if code == 429 and (
        "generaterequestsperday" in message
        or "requests per day" in message
    ):
        return False
    return code in {429, 500, 502, 503, 504}


def google_retry_delay(exc: Exception, attempt: int) -> float:
    message = str(exc)
    match = re.search(r"retry(?: in|Delay['\": ]+)\s*([0-9.]+)s", message)
    if match:
        return min(120.0, float(match.group(1)) + 1.0)
    return float(min(30, 2**attempt))


def reserve_google_request(model: str) -> float:
    configured = os.environ.get("META_HARNESS_GOOGLE_MIN_INTERVAL_SECONDS")
    interval = (
        float(configured)
        if configured is not None
        else _GOOGLE_DEFAULT_INTERVALS.get(model, 6.5)
    )
    now = time.monotonic()
    with _GOOGLE_RATE_LOCK:
        scheduled = max(now, _GOOGLE_NEXT_REQUEST_AT.get(model, now))
        _GOOGLE_NEXT_REQUEST_AT[model] = scheduled + interval
    return max(0.0, scheduled - now)


class GoogleGenAIProvider:
    name = "google"

    def __init__(self, api_key: str | None = None) -> None:
        from google import genai

        resolved_key = (
            api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        if not resolved_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Add it to .env or export it before "
                "running a Gemini model."
            )
        self.client = genai.Client(api_key=resolved_key)

    async def call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        system_prompt: str,
        tool_choice: dict[str, Any] | None,
        temperature: float | None,
        seed: int | None,
    ) -> NormalizedResponse:
        from google.genai import types

        google_tools = _google_tools(tools)
        function_config = None
        if tool_choice and tool_choice.get("type") == "tool":
            function_config = types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY,
                allowed_function_names=[str(tool_choice["name"])],
            )
        elif google_tools:
            function_config = types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.AUTO,
            )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=google_tools or None,
            tool_config=(
                types.ToolConfig(function_calling_config=function_config)
                if function_config is not None
                else None
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            max_output_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            ),
        )
        response = None
        for attempt in range(5):
            try:
                await asyncio.sleep(reserve_google_request(model))
                response = await self.client.aio.models.generate_content(
                    model=model,
                    contents=_google_contents(messages),
                    config=config,
                )
                break
            except Exception as exc:
                if not is_retryable_google_error(exc) or attempt == 4:
                    raise
                await asyncio.sleep(google_retry_delay(exc, attempt))
        if response is None:
            raise RuntimeError("Gemini request exhausted retries without a response")
        blocks: list[NormalizedContentBlock] = []
        if response.candidates and response.candidates[0].content:
            for index, part in enumerate(response.candidates[0].content.parts or [], 1):
                if part.text:
                    blocks.append(
                        NormalizedContentBlock(type="text", text=str(part.text))
                    )
                if part.function_call:
                    call = part.function_call
                    blocks.append(
                        NormalizedContentBlock(
                            type="tool_use",
                            id=call.id or f"google_call_{index}",
                            name=str(call.name),
                            input=dict(call.args or {}),
                            thought_signature=part.thought_signature,
                        )
                    )
        if not blocks:
            finish_reason = None
            if response.candidates:
                finish_reason = response.candidates[0].finish_reason
            raise RuntimeError(
                f"Gemini returned no text or function calls; finish_reason={finish_reason}"
            )
        usage = response.usage_metadata
        normalized_usage = NormalizedUsage(
            input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0)
            + int(getattr(usage, "thoughts_token_count", 0) or 0),
            cache_read_input_tokens=int(
                getattr(usage, "cached_content_token_count", 0) or 0
            ),
        )
        return NormalizedResponse(
            content=blocks,
            usage=normalized_usage,
            model=str(response.model_version or model),
        )


_MODEL_PRICING_PER_MILLION = {
    "gemini-3.7-flash": {
        "input": 1.50,
        "output": 7.50,
        "cached_input": 0.15,
        "source": "google-gemini-pricing-2026-08-16",
    },
    "gemini-3.6-flash": {
        "input": 1.50,
        "output": 7.50,
        "cached_input": 0.15,
        "source": "google-gemini-pricing-2026-08-16",
    },
    "gemini-3.5-flash-lite": {
        "input": 0.30,
        "output": 2.50,
        "cached_input": 0.03,
        "source": "google-gemini-pricing-2026-08-16",
    },
    "gemini-3.1-flash-lite": {
        "input": 0.25,
        "output": 1.50,
        "cached_input": 0.025,
        "source": "google-gemini-pricing-2026-08-16",
    },
}


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None,
) -> tuple[float, str] | None:
    pricing = _MODEL_PRICING_PER_MILLION.get(model)
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    cached = min(input_tokens, cached_tokens or 0)
    uncached = max(0, input_tokens - cached)
    cost = (
        uncached * float(pricing["input"])
        + cached * float(pricing["cached_input"])
        + output_tokens * float(pricing["output"])
    ) / 1_000_000
    return round(cost, 8), str(pricing["source"])


def get_model_provider(
    name: str,
    *,
    api_key: str | None = None,
) -> ModelProvider:
    if name == "anthropic":
        return AnthropicProvider(api_key=api_key)
    if name == "google":
        return GoogleGenAIProvider(api_key=api_key)
    raise ValueError(f"unsupported model provider: {name}")

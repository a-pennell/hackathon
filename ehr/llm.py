"""The one place this project talks to the Claude API.

Structured-output request with adaptive thinking, prompt caching on the caller's
system blocks, and server-side refusal fallbacks. Imported lazily by callers so
tests, --dry-run and --replay work without the SDK or a key.
"""

from __future__ import annotations

import json

DEFAULT_MODEL = "claude-opus-5"


def call_structured(system_blocks, messages, schema: dict, *, model: str = DEFAULT_MODEL,
                    effort: str = "high", max_tokens: int = 16000) -> dict:
    """Returns {"parsed": dict, "model": str, "usage": dict, "request_id": str|None}."""
    import anthropic

    client = anthropic.Anthropic()
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        messages=messages,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        # Routes a policy decline to a fallback model inside the same call.
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError as e:
        if "fallback" not in str(e).lower() and "beta" not in str(e).lower():
            raise
        response = client.messages.create(**kwargs)

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise RuntimeError(f"model refused the request: {getattr(details, 'category', None)} "
                           f"{getattr(details, 'explanation', '')}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("model output truncated (max_tokens); raise max_tokens or shorten the input")
    text = next(b.text for b in response.content if b.type == "text")
    usage = response.usage
    return {
        "parsed": json.loads(text),
        "model": response.model,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                  "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None)},
        "request_id": getattr(response, "_request_id", None),
    }

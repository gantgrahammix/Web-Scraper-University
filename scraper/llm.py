"""Shared Claude helper: one request in, validated JSON out."""
import json

import anthropic

from . import config


class LLMError(RuntimeError):
    pass


_client = None

# Models that accept the server-side refusal fallback parameter.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
    return _client


def available():
    return bool(config.ANTHROPIC_API_KEY)


def ask_json(system, user, schema, model=None, effort=None):
    """Return the parsed JSON object Claude produces for `schema` (structured outputs)."""
    model = model or config.CLAUDE_MODEL
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if model.startswith("claude-haiku"):
        response = client().messages.create(
            model=model, max_tokens=8000, system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
    else:
        output_config["effort"] = effort or config.CLAUDE_EFFORT
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in FALLBACK_MODELS else {}
        response = client().beta.messages.create(
            model=model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config, **extra,
        )
    if response.stop_reason == "refusal":
        raise LLMError("Claude declined this request")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude's answer was cut off (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise LLMError("Claude returned no text")
    return json.loads(text)

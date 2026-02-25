"""
LLM provider adapter — routes generation calls to the correct SDK.

Supported providers:
  anthropic  → anthropic SDK  (claude-* models)
  openai     → openai SDK     (gpt-*, o1*, o3*)
  google     → openai SDK     (gemini-*, via OpenAI-compatible endpoint)
  xai        → openai SDK     (grok-*, via OpenAI-compatible endpoint)
  perplexity → openai SDK     (all others, via OpenAI-compatible endpoint)

Public API:
  detect_provider(model_name) -> str
  get_api_key(provider, settings) -> str | None
  call_llm(prompt, model_name, settings, timeout, max_tokens, temperature) -> str
"""

import os
import logging
import re
from typing import Optional

import anthropic
import openai

from app.services.settings_service import ActiveSettings

logger = logging.getLogger(__name__)

# OpenAI-compatible base URLs per provider
_BASE_URLS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "google":     "https://generativelanguage.googleapis.com/v1beta/openai/",
    "xai":        "https://api.x.ai/v1",
    "perplexity": "https://api.perplexity.ai",
}


def clean_llm_error(exc: Exception) -> str:
    """Extract a concise, human-readable reason from an LLM provider exception.

    Specifically targets 'Quota exceeded' and 'Rate limit' details to provide
    actionable feedback without the full technical blob.
    """
    raw_msg = str(exc)

    # 1. Look for the specific Google/Gemini 'Quota exceeded' pattern
    # Pattern: * Quota exceeded for metric: <metric>, limit: <val>, model: <model>
    quota_match = re.search(r"\* (Quota exceeded for metric: [^,\n]+)", raw_msg)
    if quota_match:
        return quota_match.group(1)

    # 2. Look for Anthropic / OpenAI common rate limit phrases
    if "rate limit" in raw_msg.lower():
        # Try to find a 'retry in X seconds' part
        retry_match = re.search(r"(retry in \d+\.?\d*s)", raw_msg, re.IGNORECASE)
        if retry_match:
            return f"Rate limit exceeded ({retry_match.group(1)})"
        return "Rate limit exceeded"

    if "quota" in raw_msg.lower():
        return "Quota exceeded"

    # 3. Fallback to a truncated version of the raw message
    return raw_msg[:120].strip()


def detect_provider(model_name: str) -> str:
    """Determine which provider owns a given model ID."""
    if model_name.startswith("claude-"):
        return "anthropic"
    if model_name.startswith("gpt-") or model_name.startswith("o1") or model_name.startswith("o3"):
        return "openai"
    if model_name.startswith("gemini-"):
        return "google"
    if model_name.startswith("grok-"):
        return "xai"
    return "perplexity"


def get_api_key(provider: str, settings: ActiveSettings) -> Optional[str]:
    """Return the API key for a provider.

    For 'anthropic', falls back to the ANTHROPIC_API_KEY environment variable
    when the DB key is not set, preserving backwards compatibility.
    """
    key_map = {
        "anthropic":  settings.anthropic_api_key,
        "openai":     settings.openai_api_key,
        "google":     settings.google_api_key,
        "perplexity": settings.perplexity_api_key,
        "xai":        settings.xai_api_key,
    }
    key = key_map.get(provider)
    if not key and provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
    return key or None


def call_llm(
    prompt: str,
    model_name: str,
    settings: ActiveSettings,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call the appropriate LLM provider and return the generated text.

    Args:
        prompt:       Full prompt string to send.
        model_name:   Model ID (e.g. 'gpt-4o', 'claude-opus-4-6').
        settings:     ActiveSettings snapshot carrying provider API keys.
        timeout:      Request timeout in seconds.
        max_tokens:   Maximum tokens to generate.
        temperature:  Sampling temperature (0.0 = deterministic).

    Returns:
        Generated text string.

    Raises:
        ValueError: Required API key is not configured for the provider.
        anthropic.AuthenticationError / openai.AuthenticationError: Bad key.
        anthropic.RateLimitError / openai.RateLimitError: Rate limited.
    """
    provider = detect_provider(model_name)
    api_key = get_api_key(provider, settings)

    logger.info(
        "LLM call: provider=%s model=%s max_tokens=%d temperature=%.2f",
        provider, model_name, max_tokens, temperature,
    )

    if provider == "anthropic":
        return _call_anthropic(prompt, model_name, api_key, timeout, max_tokens, temperature)
    else:
        return _call_openai_compatible(
            prompt, model_name, provider, api_key, timeout, max_tokens, temperature
        )


def _call_anthropic(
    prompt: str,
    model_name: str,
    api_key: Optional[str],
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    message = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai_compatible(
    prompt: str,
    model_name: str,
    provider: str,
    api_key: Optional[str],
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    base_url = _BASE_URLS[provider]
    client = openai.OpenAI(api_key=api_key or "not-set", base_url=base_url, timeout=timeout)
    response = client.chat.completions.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

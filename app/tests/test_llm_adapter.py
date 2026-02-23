"""Unit tests for LLM provider routing in llm_adapter.py."""
import pytest
from unittest.mock import MagicMock, patch
from app.services.llm_adapter import detect_provider, get_api_key, call_llm


class TestDetectProvider:
    def test_claude_is_anthropic(self):
        assert detect_provider("claude-opus-4-6") == "anthropic"
        assert detect_provider("claude-sonnet-4-6") == "anthropic"
        assert detect_provider("claude-haiku-4-5-20251001") == "anthropic"

    def test_gpt_is_openai(self):
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("gpt-4o-mini") == "openai"

    def test_o_series_is_openai(self):
        assert detect_provider("o3-mini") == "openai"
        assert detect_provider("o1") == "openai"

    def test_gemini_is_google(self):
        assert detect_provider("gemini-2.0-flash") == "google"
        assert detect_provider("gemini-1.5-pro") == "google"

    def test_grok_is_xai(self):
        assert detect_provider("grok-2") == "xai"
        assert detect_provider("grok-2-vision-1212") == "xai"

    def test_unknown_is_perplexity(self):
        assert detect_provider("llama-3.1-sonar-large-128k-online") == "perplexity"
        assert detect_provider("sonar-pro") == "perplexity"


class TestGetApiKey:
    def _mock_settings(self, **kwargs):
        s = MagicMock()
        s.anthropic_api_key  = kwargs.get("anthropic_api_key", None)
        s.openai_api_key     = kwargs.get("openai_api_key", None)
        s.google_api_key     = kwargs.get("google_api_key", None)
        s.perplexity_api_key = kwargs.get("perplexity_api_key", None)
        s.xai_api_key        = kwargs.get("xai_api_key", None)
        return s

    def test_anthropic_uses_db_key(self):
        s = self._mock_settings(anthropic_api_key="sk-ant-db")
        assert get_api_key("anthropic", s) == "sk-ant-db"

    def test_anthropic_falls_back_to_env(self):
        s = self._mock_settings(anthropic_api_key=None)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}):
            assert get_api_key("anthropic", s) == "sk-ant-env"

    def test_openai_uses_db_key(self):
        s = self._mock_settings(openai_api_key="sk-openai")
        assert get_api_key("openai", s) == "sk-openai"

    def test_google_uses_db_key(self):
        s = self._mock_settings(google_api_key="AIza-google")
        assert get_api_key("google", s) == "AIza-google"

    def test_missing_key_returns_none(self):
        s = self._mock_settings()
        assert get_api_key("openai", s) is None

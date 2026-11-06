import pytest
from app.config import settings
from app.llm import LLMError, configured_provider


def test_auto_selects_groq_before_gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "groq_api_key", "groq-secret")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-secret")
    assert configured_provider() == "groq"


def test_auto_falls_back_to_gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-secret")
    assert configured_provider() == "gemini"


def test_invalid_provider_is_explicit(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "local")
    with pytest.raises(LLMError, match="LLM_PROVIDER"):
        configured_provider()

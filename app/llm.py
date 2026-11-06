"""Small provider adapter for natural-language Telegram answers."""
from __future__ import annotations

import httpx
from .config import settings


class LLMError(RuntimeError):
    """Raised when a configured LLM cannot produce an answer."""


def configured_provider() -> str | None:
    provider = settings.llm_provider.lower().strip()
    if provider not in {"auto", "groq", "gemini"}:
        raise LLMError("LLM_PROVIDER must be auto, groq, or gemini")
    if provider == "groq" and not settings.groq_api_key:
        return None
    if provider == "gemini" and not settings.gemini_api_key:
        return None
    if provider == "auto":
        if settings.groq_api_key:
            return "groq"
        if settings.gemini_api_key:
            return "gemini"
        return None
    return provider


def ask(prompt: str) -> str:
    provider = configured_provider()
    if provider is None:
        raise LLMError("No LLM provider is configured")
    if provider == "groq":
        return _ask_groq(prompt)
    return _ask_gemini(prompt)


def _ask_groq(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        timeout=25.0,
        max_retries=1,
    )
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Pishukkan, a careful personal finance assistant. "
                    "Answer only from the ledger context supplied by the user. "
                    "Never invent amounts, dates, transactions, or account details. "
                    "If the context does not answer the question, say so plainly. "
                    "Do not claim to save or change anything."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_completion_tokens=700,
    )
    content = response.choices[0].message.content
    if not content:
        raise LLMError("Groq returned an empty answer")
    return content.strip()


def _ask_gemini(prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are Pishukkan, a careful personal finance assistant. "
                        "Answer only from the ledger context supplied by the user. "
                        "Never invent amounts, dates, transactions, or account details. "
                        "If the context does not answer the question, say so plainly. "
                        "Do not claim to save or change anything."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
    }
    try:
        response = httpx.post(
            url,
            params={"key": settings.gemini_api_key},
            json=payload,
            timeout=25.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMError("Gemini request failed") from exc
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Gemini returned an empty answer")
    return text.strip()

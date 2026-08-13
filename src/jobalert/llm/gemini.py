"""Google Gemini — free tier.

    https://aistudio.google.com  ->  Get API key
"""

from __future__ import annotations

import time

from ..http import session
from ..logging_setup import get_logger
from ..settings import get_settings
from .base import LLMClient, LLMError, extract_json

log = get_logger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Free tier is tighter than Groq's — roughly 10-15 requests/minute.
MIN_INTERVAL_SECONDS = 4.5


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set but LLM_PROVIDER=gemini")
        self.model = settings.gemini_model
        self._key = settings.gemini_api_key
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        self._last_call = time.monotonic()

    def complete_json(self, system: str, user: str) -> dict:
        self._throttle()
        response = session().post(
            f"{BASE}/{self.model}:generateContent",
            params={"key": self._key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                    "maxOutputTokens": 1024,
                },
            },
            timeout=60,
        )

        if response.status_code == 429:
            raise LLMError("gemini rate limit hit — lower ENRICH_LIMIT or wait for reset")
        if not response.ok:
            raise LLMError(f"gemini {response.status_code}: {response.text[:300]}")

        payload = response.json()
        try:
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            # A safety block returns candidates without content parts.
            raise LLMError(f"unexpected gemini response shape: {str(payload)[:300]}") from exc

        return extract_json(content)

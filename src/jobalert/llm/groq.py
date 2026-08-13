"""Groq — OpenAI-compatible chat completions, free tier.

    https://console.groq.com  ->  API Keys
"""

from __future__ import annotations

import time

from ..http import session
from ..logging_setup import get_logger
from ..settings import get_settings
from .base import LLMClient, LLMError, extract_json

log = get_logger(__name__)
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Free tier is roughly 30 requests/minute. 2.2s between calls keeps us under it
# without relying on 429 retries, which burn the daily token budget.
MIN_INTERVAL_SECONDS = 2.2


class GroqClient(LLMClient):
    name = "groq"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is not set but LLM_PROVIDER=groq")
        self.model = settings.groq_model
        self._key = settings.groq_api_key
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        self._last_call = time.monotonic()

    def complete_json(self, system: str, user: str) -> dict:
        self._throttle()
        response = session().post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # Requires the word "JSON" to appear in the prompt, which it does.
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 1024,
            },
            timeout=60,
        )

        if response.status_code == 429:
            raise LLMError("groq rate limit hit — lower ENRICH_LIMIT or wait for reset")
        if not response.ok:
            raise LLMError(f"groq {response.status_code}: {response.text[:300]}")

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected groq response shape: {payload}") from exc

        return extract_json(content)

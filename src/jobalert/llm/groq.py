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


MODELS_ENDPOINT = "https://api.groq.com/openai/v1/models"


class GroqClient(LLMClient):
    name = "groq"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is not set but LLM_PROVIDER=groq")
        self.model = settings.groq_model
        self._key = settings.groq_api_key
        self._last_call = 0.0

    def preflight(self) -> None:
        """Fail once, with the answer, instead of once per job without it.

        Providers retire models. When that happens every call 404s identically,
        and the log fills with per-job failures that never say which model to
        use instead. Checking the catalogue once turns that into a single error
        naming the available options.
        """
        try:
            response = session().get(
                MODELS_ENDPOINT,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 - preflight must not mask the real run
            log.warning("could not verify the model list (%s) — continuing anyway", exc)
            return

        if response.status_code == 401:
            raise LLMError("GROQ_API_KEY was rejected (401). Create a new key at console.groq.com.")
        if not response.ok:
            log.warning("model list unavailable (%s) — continuing anyway", response.status_code)
            return

        available = sorted(
            item.get("id", "") for item in response.json().get("data", []) if item.get("id")
        )
        if self.model in available:
            return

        # Guard/whisper/TTS models cannot answer a chat completion; suggesting
        # them would send someone down a second dead end.
        chat_models = [
            name for name in available
            if not any(skip in name for skip in ("whisper", "guard", "tts", "embed"))
        ]
        raise LLMError(
            f"GROQ_MODEL '{self.model}' is not available on this key — it has most "
            f"likely been retired. Set the GROQ_MODEL repository variable to one of:\n  "
            + "\n  ".join(chat_models or available)
        )

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

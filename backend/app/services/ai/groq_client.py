import json
import logging
import time
from functools import lru_cache

from groq import Groq, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0


class GroqClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = Groq(api_key=api_key)
        self._model = model

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                logger.debug("Groq response (%d chars): %.200s", len(content), content)
                return content
            except RateLimitError as exc:
                last_error = exc
                if attempt < _RETRY_ATTEMPTS - 1:
                    logger.warning(
                        "Groq rate limit (attempt %d/%d), retrying in %.0fs",
                        attempt + 1,
                        _RETRY_ATTEMPTS,
                        _RETRY_DELAY_SECONDS,
                    )
                    time.sleep(_RETRY_DELAY_SECONDS)
            except Exception as exc:
                raise RuntimeError(f"Groq API error: {exc}") from exc
        raise RuntimeError(
            f"Groq rate limit exceeded after {_RETRY_ATTEMPTS} attempts: {last_error}"
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        raw = self.complete(system_prompt, user_prompt)
        text = raw.strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        if text.startswith("```"):
            lines = text.splitlines()
            inner: list[str] = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    inner.append(line)
            text = "\n".join(inner).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "JSON parse failure from Groq response: %s | raw: %.300s", exc, raw
            )
            return {}


@lru_cache(maxsize=1)
def get_groq_client() -> GroqClient:
    return GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)

"""A small Ollama HTTP client: health check, schema-constrained JSON chat, retries.

Why not the ``ollama`` SDK: this needs exactly two endpoints, and keeping
``requests`` as the only HTTP dependency lets the tests use ``responses`` for
both the LLM and the image downloads.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from autosieve.config import Settings

log = logging.getLogger(__name__)

# Ollama's default context window is small enough that a long description plus
# the JSON schema gets silently truncated. Ask for more explicitly.
DEFAULT_NUM_CTX = 8_192
HEALTH_TIMEOUT_S = 10.0


class LlmError(Exception):
    """Base class for LLM-layer failures."""


class OllamaUnavailableError(LlmError):
    """Ollama cannot be reached, or kept failing after retries."""


class ModelNotFoundError(LlmError):
    """The configured model is not pulled on this Ollama server."""


class OllamaResponseError(LlmError):
    """Ollama answered, but not with something we can use. Not retried."""


def model_matches(configured: str, available: str) -> bool:
    """``llama3.1`` matches ``llama3.1:latest``; an explicit tag must match exactly."""
    if configured == available:
        return True
    return ":" not in configured and available == f"{configured}:latest"


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse the model's text as a JSON object, tolerating fences and stray prose."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise OllamaResponseError(f"model output was not JSON: {text[:120]!r}") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OllamaResponseError(f"model output was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise OllamaResponseError("model output was JSON but not an object")
    return data


@dataclass
class OllamaClient:
    host: str
    model: str
    timeout_s: float = 120.0
    retry_attempts: int = 3
    retry_delay_s: float = 2.0
    num_ctx: int = DEFAULT_NUM_CTX
    session: requests.Session = field(default_factory=requests.Session)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaClient:
        return cls(
            host=settings.ollama_host,
            model=settings.ollama_model,
            timeout_s=settings.llm_timeout_s,
            retry_attempts=settings.retry_attempts,
            retry_delay_s=settings.retry_delay_s,
        )

    # ── endpoints ────────────────────────────────────────────────────────────

    def health_check(self) -> list[str]:
        """Fail fast if Ollama is down or the model is missing. Returns available model names."""
        try:
            resp = self.session.get(f"{self.host}/api/tags", timeout=HEALTH_TIMEOUT_S)
            resp.raise_for_status()
            payload = resp.json()
            models = [str(m["name"]) for m in payload.get("models", [])]
        except requests.RequestException as exc:
            raise OllamaUnavailableError(
                f"cannot reach Ollama at {self.host}: {exc}. Is `ollama serve` running?"
            ) from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise OllamaResponseError(f"unexpected /api/tags response: {exc}") from exc

        if not any(model_matches(self.model, name) for name in models):
            available = ", ".join(models) or "none"
            raise ModelNotFoundError(
                f"model {self.model!r} is not available on {self.host}. "
                f"Run `ollama pull {self.model}`. Available: {available}"
            )
        return models

    def chat_json(self, *, system: str, user: str, schema: dict[str, object]) -> dict[str, Any]:
        """One chat turn whose output Ollama constrains to ``schema``. Returns the parsed object.

        Transport errors and 5xx responses are retried. A 4xx or an unparseable
        body is a programming or model problem and is raised immediately.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                resp = self.session.post(
                    f"{self.host}/api/chat", json=payload, timeout=self.timeout_s
                )
                if 400 <= resp.status_code < 500:
                    raise OllamaResponseError(
                        f"Ollama rejected the request ({resp.status_code}): {resp.text[:200]}"
                    )
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                if not isinstance(content, str):
                    raise OllamaResponseError("message.content was not a string")
                return parse_json_object(content)
            except OllamaResponseError:
                raise
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                last_error = exc
                log.warning("Ollama attempt %d/%d failed: %s", attempt, self.retry_attempts, exc)
                if attempt < self.retry_attempts:
                    self.sleep(self.retry_delay_s)
        raise OllamaUnavailableError(
            f"Ollama failed after {self.retry_attempts} attempts: {last_error}"
        ) from last_error

"""Ask the model for a structured :class:`Analysis` of one listing."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from autosieve.llm.client import LlmError, OllamaClient
from autosieve.llm.prompts import SYSTEM_PROMPT, build_fewshot_messages, build_user_message
from autosieve.models import Analysis, Listing

log = logging.getLogger(__name__)


class AnalysisError(LlmError):
    """The model answered, but not with a valid analysis."""


class ListingAnalyzer:
    def __init__(self, client: OllamaClient, *, use_fewshot: bool = True) -> None:
        self._client = client
        self._schema = Analysis.ollama_schema()
        self._examples = build_fewshot_messages() if use_fewshot else None

    @property
    def model(self) -> str:
        return self._client.model

    def analyse(self, listing: Listing) -> Analysis:
        data = self._client.chat_json(
            system=SYSTEM_PROMPT,
            user=build_user_message(listing),
            schema=self._schema,
            examples=self._examples,
        )
        try:
            return Analysis.model_validate(data)
        except ValidationError as exc:
            raise AnalysisError(
                f"model output for listing {listing.id} failed validation "
                f"({exc.error_count()} error(s)): {exc.errors()[0].get('msg', '')}"
            ) from exc

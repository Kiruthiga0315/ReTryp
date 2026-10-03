"""LLM routing: provider chain, one retry, then template text.

Rules from the spec, implemented here:

* Structured JSON output, validated with Pydantic.
* One retry on invalid output, then fall back.
* Fall through the chain on error or rate limit.
* Cache generated explanations by plan ID and version.
* Keep prompts small: send structured plan data only.
* Never show chain-of-thought. Only concise decision factors.

Every response records which writer produced it (``source``), so the UI can
label template text honestly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError

from ..config import Settings
from .base import LLMError, LLMRequest, LLMUnavailable
from .gemini import GeminiClient
from .openai_compat import OpenAICompatibleClient

__all__ = ["LLMError", "LLMRequest", "LLMUnavailable", "GeminiClient", "OpenAICompatibleClient"]

SYSTEM_PROMPT = (
    "You write short operational notes for a corporate travel recovery tool. "
    "Use plain, factual English. Never use marketing language, never mention "
    "artificial intelligence or assistants, and never invent facts that are "
    "not in the supplied data. Do not include reasoning steps. Write in the "
    "third person about the traveller's itinerary."
)


class PlanExplanation(BaseModel):
    """Validated shape for a plan explanation."""

    headline: str
    body: str
    tradeoffs: list[str] = []


class ParsedDisruption(BaseModel):
    """Validated shape for unstructured disruption text."""

    kind: str
    delay_minutes: int | None = None
    service_number: str | None = None
    airport_code: str | None = None
    confidence_note: str | None = None


@dataclass
class LLMResult:
    value: dict
    source: str  # llm provider name, or "template"
    model: str | None = None
    cached: bool = False
    error: str | None = None


@dataclass
class _CacheEntry:
    value: dict
    stored_at: datetime


@dataclass
class LLMRouter:
    settings: Settings
    _cache: dict[str, _CacheEntry] = field(default_factory=dict)

    def _primary(self):
        settings = self.settings
        if not settings.llm_provider:
            return None
        if settings.llm_provider == "gemini":
            if not settings.llm_api_key:
                return None
            return GeminiClient(settings.llm_api_key, settings.llm_model, settings.llm_timeout_seconds)
        if settings.llm_provider == "openai_compatible":
            # A named provider with no key is the same as no provider at all:
            # the template writer answers. Constructing the client would raise
            # from its constructor and break the request.
            if not settings.llm_api_key:
                return None
            return OpenAICompatibleClient(
                settings.llm_api_key,
                settings.llm_model,
                settings.llm_base_url or "https://api.groq.com/openai/v1",
                settings.llm_timeout_seconds,
                name=_compatible_name(settings.llm_base_url),
            )
        return None

    def _secondary(self):
        settings = self.settings
        if not settings.llm_fallback_provider:
            return None
        if settings.llm_fallback_provider == "gemini":
            if not settings.llm_fallback_api_key:
                return None
            return GeminiClient(
                settings.llm_fallback_api_key,
                settings.llm_fallback_model or settings.llm_model,
                settings.llm_timeout_seconds,
            )
        if settings.llm_fallback_provider == "openai_compatible":
            if not settings.llm_fallback_api_key:
                return None
            return OpenAICompatibleClient(
                settings.llm_fallback_api_key,
                settings.llm_fallback_model or settings.llm_model,
                settings.llm_fallback_base_url or settings.llm_base_url,
                settings.llm_timeout_seconds,
                name=_compatible_name(settings.llm_fallback_base_url),
            )
        return None

    def chain(self) -> list:
        return [c for c in (self._primary(), self._secondary()) if c is not None]

    def cache_key(self, namespace: str, *parts: object) -> str:
        digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:32]
        return f"{namespace}:{digest}"

    def cached(self, key: str) -> dict | None:
        entry = self._cache.get(key)
        return entry.value if entry else None

    def store(self, key: str, value: dict) -> None:
        self._cache[key] = _CacheEntry(value=value, stored_at=datetime.now(timezone.utc))

    async def generate(
        self,
        *,
        namespace: str,
        cache_parts: tuple,
        user_prompt: str,
        schema: type[BaseModel],
        template: dict,
        max_tokens: int = 600,
    ) -> LLMResult:
        """Generate validated JSON, falling back to template text.

        ``template`` must already be a complete, usable answer. It is what the
        product shows when no key is configured, and it must never look like
        an error state.
        """
        key = self.cache_key(namespace, *cache_parts)
        hit = self.cached(key)
        if hit is not None:
            return LLMResult(value=hit, source=hit.get("_source", "template"), model=hit.get("_model"), cached=True)

        clients = self.chain()
        if not clients:
            return LLMResult(value={**template, "_source": "template"}, source="template")

        last_error: str | None = None
        for client in clients:
            for attempt in range(2):  # one retry, per the spec
                try:
                    raw = await client.complete_json(
                        LLMRequest(
                            system=SYSTEM_PROMPT,
                            user=user_prompt,
                            json_schema_hint="Return a single JSON object.",
                            max_output_tokens=max_tokens,
                        )
                    )
                    validated = schema.model_validate(raw)
                    value = validated.model_dump()
                    value["_source"] = client.name
                    value["_model"] = client.model
                    self.store(key, value)
                    return LLMResult(value=value, source=client.name, model=client.model)
                except (LLMError, ValidationError) as exc:
                    last_error = str(exc)
                    if attempt == 0:
                        continue  # retry once with the same provider
                    break  # move to the next provider in the chain

        return LLMResult(
            value={**template, "_source": "template"},
            source="template",
            error=last_error,
        )


def _compatible_name(base_url: str | None) -> str:
    url = (base_url or "").lower()
    if "groq" in url:
        return "groq"
    if "openrouter" in url:
        return "openrouter"
    if "localhost" in url or "127.0.0.1" in url:
        return "ollama"
    return "openai_compatible"


def build_router(settings: Settings) -> LLMRouter:
    return LLMRouter(settings=settings)


__all__ = [
    "LLMResult",
    "LLMRouter",
    "LLMUnavailable",
    "ParsedDisruption",
    "PlanExplanation",
    "build_router",
]

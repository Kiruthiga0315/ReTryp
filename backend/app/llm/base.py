"""LLM provider interface.

The product works with no LLM key at all. Deterministic code does
feasibility, cost, timing and scoring; the LLM is only ever asked to turn
structured facts into readable sentences. If every provider fails, the
template writer takes over and the response says so.

Nothing here is exposed to the frontend as an "AI" feature. The interface
copy is "explanation", "wording", "help".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMRateLimited(LLMError):
    pass


class LLMUnavailable(LLMError):
    """No provider is configured, or all providers failed."""


@dataclass
class LLMRequest:
    system: str
    user: str
    json_schema_hint: str | None = None
    max_output_tokens: int = 700
    temperature: float = 0.2


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


class LLMClient(Protocol):
    name: str
    model: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def complete_json(self, request: LLMRequest) -> dict: ...

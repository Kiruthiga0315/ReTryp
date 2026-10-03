"""OpenAI-compatible client.

Covers Groq, OpenRouter (including the ``:free`` model variants) and a local
Ollama server, all through the same chat-completions shape. Which one is in
use is decided entirely by ``LLM_BASE_URL`` and ``LLM_MODEL``.
"""

from __future__ import annotations

import json

import httpx

from .base import LLMError, LLMRateLimited, LLMRequest, LLMResponse


class OpenAICompatibleClient:
    name = "openai_compatible"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 20.0,
        name: str | None = None,
    ) -> None:
        if not model:
            raise LLMError("LLM_MODEL is not set")
        # Ollama does not require a key; hosted endpoints do.
        if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
            raise LLMError("LLM_API_KEY is not set")
        self._key = api_key
        self.model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        if name:
            self.name = name

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return headers

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.json_schema_hint:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.post(
                f"{self._base}/chat/completions", headers=self._headers(), json=payload
            )
            if response.status_code == 429:
                raise LLMRateLimited(f"{self.name} rate limit")
            if response.status_code >= 400:
                raise LLMError(f"{self.name} error {response.status_code}: {response.text[:200]}")
            body = response.json()

        choices = body.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name} returned no choices")
        text = (choices[0].get("message") or {}).get("content", "").strip()
        if not text:
            raise LLMError(f"{self.name} returned empty content")
        return LLMResponse(text=text, provider=self.name, model=self.model)

    async def complete_json(self, request: LLMRequest) -> dict:
        response = await self.complete(request)
        cleaned = response.text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self.name} returned invalid JSON: {exc}") from exc

"""Gemini client, implemented natively against the REST API.

The model name is a single configuration value (``LLM_MODEL``), never
hard-coded at a call site. The default in ``config.py`` is a Flash-Lite
Gemini model, chosen because the free tier comfortably covers the small
number of short generations this product makes.
"""

from __future__ import annotations

import json

import httpx

from .base import LLMError, LLMRateLimited, LLMRequest, LLMResponse

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise LLMError("Gemini API key is not set")
        self._key = api_key
        self.model = model
        self._timeout = timeout

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        if request.json_schema_hint:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        url = f"{API_ROOT}/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.post(
                url, params={"key": self._key}, json=payload
            )
            if response.status_code == 429:
                raise LLMRateLimited("Gemini rate limit")
            if response.status_code >= 400:
                raise LLMError(f"Gemini error {response.status_code}: {response.text[:200]}")
            body = response.json()

        text = _extract_text(body)
        if not text:
            raise LLMError("Gemini returned no text")
        return LLMResponse(text=text, provider=self.name, model=self.model)

    async def complete_json(self, request: LLMRequest) -> dict:
        response = await self.complete(request)
        return _parse_json(response.text)


def _extract_text(body: dict) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Gemini returned invalid JSON: {exc}") from exc

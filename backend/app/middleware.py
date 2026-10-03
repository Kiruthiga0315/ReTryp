"""Middleware that establishes the viewer's display currency per request.

Runs before routing so every serializer that calls ``convert_minor`` sees the
same context. Rate fetching is cached by the provider registry, so this is a
cheap lookup on the hot path.
"""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import get_settings
from .db import SessionLocal
from .display import (
    DisplayContext,
    current_display,
    reset_display_context,
    set_display_context,
)
from .providers.fx import get_rates
from .security import token_from_request, user_from_token

AUTH_ONLY_PREFIXES = ("/api/",)


class DisplayCurrencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(AUTH_ONLY_PREFIXES):
            return await call_next(request)

        token = set_display_context(None)
        try:
            await self._attach(request)
        except Exception:
            # A currency lookup must never break a request; fall back to no
            # conversion and let the endpoint run with stored amounts.
            set_display_context(None)
        try:
            response = await call_next(request)
        except Exception:
            reset_display_context(token)
            raise
        context = current_display()
        if context is not None:
            response.headers["X-Retryp-FX"] = json.dumps(context.to_dict())
        reset_display_context(token)
        return response

    async def _attach(self, request: Request) -> None:
        settings = get_settings()
        session = SessionLocal()
        try:
            user = user_from_token(session, token_from_request(request))
            if user is None:
                return
            # The viewer's preferred currency wins; otherwise their budget
            # currency; otherwise the product default (INR). Stored amounts
            # keep the currency the provider quoted.
            preferred = (
                str((user.settings or {}).get("currency") or "").upper()
                or (user.budget_currency or "").upper()
                or settings.fx_display_currency.upper()
            )
            rates = await get_rates(settings)
            if rates is not None:
                set_display_context(DisplayContext(target_currency=preferred, rates=rates))
        finally:
            session.close()


__all__ = ["DisplayCurrencyMiddleware"]

"""Display-currency conversion for API payloads.

Amounts are stored in the currency their provider quoted. A viewer sees them
in their preferred currency, converted with a rate whose provenance travels
with the response:

* the converted minor units and currency code, and
* a per-response ``fx`` block naming the rate source and its provenance.

Nothing here alters stored values or plan scoring; it is presentation only.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from .domain.money import Money, convert, exponent
from .providers.fx import RateSet


@dataclass(frozen=True, slots=True)
class DisplayContext:
    """The currency the viewer asked to see amounts in, plus the rates."""

    target_currency: str
    rates: RateSet

    def to_dict(self) -> dict:
        target = self.target_currency.upper()
        return {
            "display_currency": target,
            "rate_base": self.rates.base,
            "rate_to_display": self.rates.rate_to(target),
            "rate_provenance": self.rates.provenance,
            "rate_as_of": self.rates.as_of.isoformat() if self.rates.as_of else None,
        }


_ctx: ContextVar[DisplayContext | None] = ContextVar("display_currency", default=None)


def set_display_context(context: DisplayContext | None):
    return _ctx.set(context)


def reset_display_context(token) -> None:
    _ctx.reset(token)


def current_display() -> DisplayContext | None:
    return _ctx.get()


def fx_block() -> dict | None:
    context = _ctx.get()
    return context.to_dict() if context else None


def convert_minor(minor: int | None, currency: str | None) -> tuple[int | None, str | None]:
    """Convert an amount into the viewer's currency, if one is set.

    Falls back to the stored amount when no usable rate exists, so a figure is
    never dropped or guessed.
    """
    stored_currency = (currency or "EUR").upper()
    if minor is None:
        return None, stored_currency

    context = _ctx.get()
    target = context.target_currency.upper() if context else stored_currency
    if context is None or target == stored_currency:
        return minor, stored_currency

    target_rate = context.rates.rate_to(target)
    source_rate = context.rates.rate_to(stored_currency)
    if target_rate is None or source_rate is None:
        return minor, stored_currency

    cross_rate = target_rate / source_rate
    converted = convert(Money(minor, stored_currency), cross_rate, target)
    return converted.amount_minor, converted.currency


def format_minor(minor: int, currency: str) -> str:
    return str(Money(minor, currency))


__all__ = [
    "DisplayContext",
    "convert_minor",
    "current_display",
    "format_minor",
    "fx_block",
    "reset_display_context",
    "set_display_context",
    "exponent",
]

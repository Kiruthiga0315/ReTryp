"""Money handling.

Amounts are integer minor units plus an ISO-4217 currency code. Floats are
never used for money anywhere in the domain.
"""

from __future__ import annotations

from dataclasses import dataclass

MINOR_UNITS: dict[str, int] = {
    "EUR": 2,
    "USD": 2,
    "GBP": 2,
    "INR": 2,
    "CHF": 2,
    "SEK": 2,
    "NOK": 2,
    "DKK": 2,
    "JPY": 0,
}


def exponent(currency: str) -> int:
    return MINOR_UNITS.get(currency.upper(), 2)


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", self.currency.upper())

    def __add__(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValueError(
                f"cannot add {self.currency} to {other.currency}; convert first"
            )
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValueError(
                f"cannot subtract {other.currency} from {self.currency}; convert first"
            )
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def scaled(self, factor: float) -> "Money":
        return Money(round(self.amount_minor * factor), self.currency)

    @property
    def is_zero(self) -> bool:
        return self.amount_minor == 0

    @property
    def is_negative(self) -> bool:
        return self.amount_minor < 0

    def __str__(self) -> str:
        exp = exponent(self.currency)
        if exp == 0:
            return f"{self.currency} {self.amount_minor:,}"
        sign = "-" if self.amount_minor < 0 else ""
        whole, frac = divmod(abs(self.amount_minor), 10**exp)
        return f"{sign}{self.currency} {whole:,}.{frac:0{exp}d}"


ZERO_EUR = Money(0, "EUR")


def from_major(value: float | int, currency: str) -> Money:
    exp = exponent(currency)
    return Money(round(float(value) * (10**exp)), currency)


def convert(amount: Money, rate: float, target_currency: str) -> Money:
    """Convert using an explicitly supplied rate.

    Rates are never hard-coded in domain logic; callers pass a rate from a
    provider so provenance stays honest.
    """
    if amount.currency == target_currency.upper():
        return amount
    exp = exponent(target_currency)
    return Money(round(amount.amount_minor * rate * (10 ** (exp - exponent(amount.currency)))), target_currency)

"""Template wording.

These are the sentences the product shows when no LLM key is configured, or
when every provider fails. They are written as finished product copy, not as
placeholders, and they are built from the same structured plan data the LLM
would receive. A traveller must never be able to tell which writer produced
a given sentence except through the provenance label.
"""

from __future__ import annotations

from ..domain.timeutil import format_duration


def plan_headline(label: str, title: str, arrival_delta_minutes: int) -> str:
    if arrival_delta_minutes <= 0:
        return f"Plan {label}: {title}. Arrives as originally planned."
    return f"Plan {label}: {title}. Arrives {format_duration(arrival_delta_minutes)} later."


def plan_body(plan: dict) -> str:
    """A short paragraph describing a plan, built from its own fields."""
    parts: list[str] = []
    title = plan.get("title", "Recovery plan")
    parts.append(f"{title}.")

    segments = plan.get("segments") or []
    if segments:
        first = segments[0]
        parts.append(
            f"Travel {first.get('origin_code')} to {first.get('destination_code')} on "
            f"{first.get('service_number')} departing {first.get('departure_local')}."
        )

    cost_minor = plan.get("additional_cost_minor", 0)
    currency = plan.get("currency", "EUR")
    if cost_minor:
        exp = 2
        whole, frac = divmod(abs(cost_minor), 10**exp)
        parts.append(f"Additional cost {currency} {whole}.{frac:02d}.")
    else:
        parts.append("No additional cost.")

    changes = plan.get("changes_count")
    if changes:
        parts.append(f"{changes} booking change{'s' if changes != 1 else ''} required.")

    hotels = plan.get("hotel_changes") or []
    for change in hotels:
        parts.append(change.get("detail", ""))

    ground = plan.get("ground_transport") or []
    if ground:
        parts.append(f"Ground transfer rebooked for {ground[0].get('pickup_local')}.")

    safety = plan.get("connection_safety")
    if safety == "safe":
        parts.append("All connections feasible.")
    elif safety == "tight":
        parts.append("One connection is tight.")

    return " ".join(p for p in parts if p)


def plan_tradeoffs(plan: dict) -> list[str]:
    """Concise decision factors, phrased as trade-offs."""
    out: list[str] = []
    delta = plan.get("arrival_delta_minutes", 0)
    if delta > 0:
        out.append(f"Arrives {format_duration(delta)} later than the original itinerary")
    cost = plan.get("additional_cost_minor", 0)
    if cost:
        out.append(f"Adds {plan.get('currency', 'EUR')} {cost / 100:.2f} to the trip cost")
    else:
        out.append("No additional cost")
    if plan.get("hotel_nights_added"):
        out.append("Requires an extra hotel night")
    if plan.get("hotel_nights_lost"):
        out.append("Gives up a booked hotel night")
    if not plan.get("ground_transport_ok", True):
        out.append("Ground transport could not be rebooked")
    return out


def disruption_notification(disruption: dict) -> dict:
    """Human wording for a disruption alert."""
    kind = disruption.get("kind", "")
    service = disruption.get("service_number") or "your flight"
    origin = disruption.get("origin_code") or ""
    destination = disruption.get("destination_code") or ""

    if kind == "flight_delay":
        delay = format_duration(disruption.get("delay_minutes", 0))
        title = f"{service} delayed {delay}"
        body = (
            f"{service} from {origin} to {destination} is delayed {delay}. "
            f"The new estimated arrival is {disruption.get('new_arrival_local', 'not yet published')}. "
            "Recovery options are ready to review."
        )
    elif kind == "flight_cancellation":
        title = f"{service} cancelled"
        body = (
            f"{service} from {origin} to {destination} has been cancelled. "
            "A replacement on this leg is required."
        )
    elif kind == "missed_connection":
        title = f"Connection at {origin} missed"
        body = (
            f"You will not make the {service} connection at {origin}. "
            "Replacement options are being prepared."
        )
    elif kind == "weather":
        title = f"Weather affecting {origin}"
        body = (
            f"Conditions at {origin} are affecting operations. "
            "This is likely to be treated as extraordinary circumstances for compensation."
        )
    elif kind == "hotel_cancellation":
        title = "Hotel booking affected"
        body = "The hotel booking has been affected. An alternative is being prepared."
    elif kind == "ground_transport_disruption":
        title = "Ground transport disrupted"
        body = "The transfer booking has been affected and needs to be rebooked."
    elif kind == "visa_transit":
        title = "Transit restriction"
        body = (
            "A visa or transit restriction affects this itinerary. "
            "Verify with the embassy or airline before travel."
        )
    else:
        title = "Journey disrupted"
        body = "The itinerary has been disrupted. Recovery options are being prepared."

    return {"title": title, "body": body}


def execution_confirmation(action: dict) -> str:
    """Copy for an executed action, honest about what actually happened."""
    status = action.get("status", "change_requested")
    description = action.get("description", "Booking change")
    if status == "recorded_offline":
        return f"{description} — recorded. No live booking provider was contacted."
    if status == "pending_provider_confirmation":
        return f"{description} — pending provider confirmation."
    return f"{description} — change requested."


def help_answer(topic: str, context: dict) -> str:
    """Answers for the contextual help panel, from structured facts only."""
    if topic == "why_recommended":
        factors = context.get("factors") or []
        if not factors:
            return "This plan scored highest on arrival time, cost and connection safety."
        return "This plan scored highest overall. " + " ".join(f"{f}." for f in factors[:4])
    if topic == "cheaper":
        alternatives = context.get("cheaper") or []
        if not alternatives:
            return "This is already the lowest-cost feasible plan for the disrupted leg."
        best = alternatives[0]
        return (
            f"{best.get('title')} costs {best.get('additional_cost_display')} less, "
            f"but arrives {best.get('arrival_delta_display')} later."
        )
    if topic == "do_nothing":
        return (
            "Without a change, the connection at "
            f"{context.get('airport_code', 'the transfer airport')} is missed and the onward "
            "booking is forfeited. The hotel booking and the transfer would both need to be dealt with."
        )
    if topic == "connection":
        buffer_minutes = context.get("buffer_minutes")
        required = context.get("required_minutes")
        if buffer_minutes is None:
            return "No connection is affected by this plan."
        return (
            f"This plan leaves {buffer_minutes} minutes at the connection, against a "
            f"{required} minute minimum. Connection maintained."
        )
    if topic == "compensation":
        outcome = context.get("outcome", "not_eligible")
        if outcome == "potential_eligibility":
            return (
                f"Potential eligibility of {context.get('amount_display')}. "
                "This is an estimate, not a guarantee."
            )
        return "No compensation is estimated for this disruption under the applicable rules."
    return "No answer is available for that question with the current data."

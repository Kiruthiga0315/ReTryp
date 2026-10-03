# AGENTS.md — ReTryp working notes

## Layout

* `backend/` — Python 3.11+ FastAPI app. `app/domain` holds pure domain logic (no I/O),
  `app/agents` the LangGraph nodes/services, `app/providers` external data behind
  interfaces, `app/llm` the swappable LLM layer, `app/routers` HTTP + SSE.
* `frontend/` — React + TypeScript (Vite), TanStack Query, React Router.
* `docs/FACTCHECK.md` — every hard-coded regulatory/provider fact with source URL + date.

## Service coverage (`journey` and `recovery`)

Two real sources answer "what can I travel on this leg", in order:

1. A live flight provider (AeroDataBox / AviationStack / FlightAware), when one
   is configured, plus the loaded DELFI/GTFS.de rail timetable.
2. `app/domain/itineraries.py` — two real legs from the loaded timetable
   stitched through a hub, timed against
   `app/domain/connections.assess_connection`. Nothing is modelled: a pair the
   data cannot bridge yields no itinerary, and the itinerary's provenance is
   the weakest of its legs.

There is no sample or modelled catalogue. When no source can answer, the leg
returns an empty list and the coverage the datasets actually hold, never an
invented row. Recovery uses the same sources via `app/providers/options.py`.
Never present a modelled row as a published schedule, and never label a cached
or reference value as live.

## Commands

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
alembic upgrade head && python -m app.bootstrap   # creates the sign-in accounts
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev -- --port 3000
```

## Conventions

* Domain logic in `app/domain/*` must stay import-light and side-effect free so it is
  trivially unit-testable. Routers do I/O, domain does arithmetic.
* All datetime handling: store UTC, convert with `zoneinfo` for display. Never naive.
* Money: integer minor units + ISO-4217 currency code, never floats.
* Provenance is a first-class field on every outward-facing model. If you add a data
  point to an API response, it needs `provenance` (and `fetched_at` for CACHED).
* UI: status is always colour + icon + text label. Never colour alone.
* No AI branding anywhere in the frontend.

## Gotchas

* Recovery plan letters are assigned in `agents/pipeline.py` *after* scoring, so
  the list reads A, B, C, D with the recommended plan always A. Do not letter
  plans in `build_plan_drafts`; build order is not the preference order.
* Any endpoint that totals money across plans must convert each amount into the
  viewer's display currency first (`display.convert_minor`), never assume a
  single currency. `GET /trips/{id}/history` returns the `currency` it used.
* No trips are seeded. `python -m app.bootstrap` creates the three sign-in
  accounts only; trips come from the Journey Builder. Heredoc edits: run one
  command at a time or chain with ``&&``; the terminal rejects multiple
  top-level commands in one call.
* `app/data/*.json` is downloaded by `python -m scripts.build_reference` and
  `python -m scripts.build_rail`; it is badged REFERENCE, not LIVE.
* `find_recovery_target` returns a target for the disrupted leg itself when it
  is the journey's *last* leg (`origin_leg=True`), not only when a downstream
  connection breaks. Without this a delayed single-leg trip produced no plans.
  When it does return `None` — an intermediate delay the connection absorbs —
  `generate_plans` still calls `build_plan_drafts`, which emits the one
  "keep the existing itinerary" plan. Both shapes persist through
  `_persist_plans`, so scoring, lettering and explanations stay in one place.
* AviationStack publishes **one row per marketing number**, so a single physical
  flight arrives several times under codeshare partners. `_collapse_codeshares`
  in `providers/flights.py` folds rows that name the same operating flight and
  departure into one option. An operator's own row has `codeshared: null`; a
  partner's row names the operator. Do not sort or count raw provider rows
  without collapsing first.
* A flight designator's carrier code can contain a digit (`6E` IndiGo, `B6`
  JetBlue, `U2` easyJet), so never derive it by taking only the letters — that
  yields `E`. Use `_carrier_code`.
* The free AviationStack plan serves `/flights` (real-time, exact pair,
  effectively today) but restricts `flightsFuture`. A date outside the window is
  `UNAVAILABLE`, never back-filled from another source.
* A provider row for a journey already finished is a past fact, not a live
  service: `stale_when_landed` is set and `/api/journey/options` badges it
  `CACHED`. The leg badge follows its rows, so an all-landed leg is `CACHED`.

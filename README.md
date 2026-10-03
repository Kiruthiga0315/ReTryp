# ReTryp

Autonomous trip recovery. ReTryp holds a traveller's whole journey — flights,
rail, buses, transfers, rental cars and hotels across multiple destinations —
and when something breaks it works out the effect on the entire trip, builds
complete recovery plans, compares them, and applies the one a traveller
approves.

AI is the engine, never the interface. There are no agent names, confidence
scores or "AI recommends" labels anywhere in the product. Deterministic code
does the feasibility, cost, timing and scoring; the optional language model is
only used to phrase explanations, parse free-text disruption reports, and
answer the small contextual help panel.

## What it does

* Holds a multi-modal itinerary with connections and deadlines between legs.
* Detects a disruption and works out the cascading effects on later legs,
  hotels and ground transport.
* Builds three or more complete, feasible plans and scores them on arrival
  time, total travel time, additional cost, connection safety, number of
  changes, hotel impact, ground transport, preferences, visa and transit
  restrictions, disruption likelihood and operational risk.
* Presents a comparison, takes an explicit approval, applies the plan and keeps
  monitoring. A second disruption starts a fresh recovery cycle.
* Estimates passenger-rights eligibility for EU261/2004 and India's DGCA rules.

Every data point carries provenance — **LIVE**, **CACHED** (with a fetched-at
time), **REFERENCE**, **SIMULATED** or **UNAVAILABLE** — as a badge on the card,
row or plan, plus a global data-status indicator in the header. There is no
sample or demonstration catalogue: a trip is one a traveller built, and a source
that cannot answer says so rather than being filled in.

## Architecture

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, TanStack Query, React Router, Leaflet |
| Backend | Python, FastAPI, REST + OpenAPI, Server-Sent Events |
| Orchestration | LangGraph recovery graph |
| Global Transit | OpenTripPlanner (OTP) self-hosted cluster with global GTFS feeds |
| Live Scraping | Apify 12Go Asia Multi-Modal Scraper |
| Database | SQLite by default; PostgreSQL via `DATABASE_URL`; Alembic migrations |

```
backend/app
  domain/      pure logic: connections, scoring, compensation, visa, geo, time
  agents/      the recovery graph and its typed nodes (never named in the UI)
  providers/   flights, hotels, ground transport, weather, maps — behind interfaces
  llm/         swappable language providers with template fallback
  routers/     HTTP endpoints and the SSE stream
frontend/src
  pages/       Dashboard, Active Journey, Recovery Center, Plan detail, Map,
               My Trips, Bookings, Notifications, History, Profile, Settings
  components/  the design system and domain components
  api/         typed client and query hooks
```

## The recovery pipeline

```
detect ─▶ assess ─▶ search ─▶ constrain ─▶ generate ─▶ score ─▶ present
                                                                  │
                                          ┌───────────────────────┘
                                          ▼
                             human approval (graph interrupt, resumable)
                                          │
                                          ▼
                                     execute ─▶ monitor ──▶ (re-enter on escalation)
```

* **detect** — a disruption arrives from a live feed or the Scenario Simulator.
* **assess** — impact on the disrupted leg and every downstream connection,
  hotel check-in and transfer.
* **search** — alternatives for each affected leg from the provider interfaces.
* **constrain** — visa and transit rules, policy, baggage, budget, preferences.
* **generate** — full candidate plans, one mode per leg, never redundant.
* **score** — a deterministic weighted score; factors are plain language.
* **present** — the Recovery Center and the comparison table.
* **approval** — the graph pauses on a resumable interrupt until a person confirms.
* **execute** — idempotent application of each change, written to the audit log.
* **monitor** — watches the active plan; an invalidation re-enters the graph.

## Running it locally

Requires Python 3.11+ and Node 20+.

### Backend

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
BOOTSTRAP_PASSWORD='choose-a-password' python -m app.bootstrap   # creates the sign-in accounts
uvicorn app.main:app --reload --port 8000
```

API docs are at http://localhost:8000/docs.

### Frontend

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

Open http://localhost:3000 and sign in.

### Accounts

ReTryp seeds no trips. The bootstrap command creates three sign-in accounts and
prints a generated password unless `BOOTSTRAP_PASSWORD` is set.

| Role | Email |
| --- | --- |
| Traveller | `traveller@retryp.example` |
| Travel manager | `manager@retryp.example` |
| Admin | `ops@retryp.example` |

Change the addresses and password before any real deployment.

## Building a trip

Sign in, open **Build Journey**, choose the places you are travelling between,
pick a service for each leg, and build the journey. Every option is badged with
where it came from; a pair the data cannot answer for returns an honest empty
state and the coverage the datasets actually hold instead of an invented row.

Once a trip exists, administrators see the **Scenario simulator**. A live feed
cannot be asked to produce a chosen disruption on demand, so the simulator
injects one — a delay with minutes, a cancellation, a missed connection, a
weather or airport event, a hotel cancellation, and so on. Everything it creates
is tagged SIMULATED and enters the same detection, impact and recovery pipeline
a live feed would use. A useful first run is a long-haul leg delayed by 3h 45m:
ReTryp finds the connection is no longer feasible against the minimum connection
time, shifts the onward arrival, flags the hotel for a late-arrival notice or a
shifted night, rebooks the transfer, and offers three or more comparable plans
across modes. Approve one and the itinerary and map update. Inject a second
disruption to start a new cycle.

## Data sources

All external data sits behind a provider interface, with per-provider caching,
exponential backoff with jitter, and a circuit breaker. No API key is ever sent
to or exposed in the frontend.

| Need | Sources |
| --- | --- |
| Flight schedules and status | AeroDataBox, AviationStack or FlightAware AeroAPI |
| Aircraft positions | OpenSky |
| Airport, airline, route reference | OpenFlights, OurAirports |
| Delay-risk priors | BTS (US only), DGCA reports (India), Eurocontrol and UK CAA (Europe) |
| Ground transport | GTFS static and GTFS-Realtime via Transitland and the Mobility Database |
| Maps and routing | OpenStreetMap tiles, Nominatim, OSRM |
| Weather | Open-Meteo (IMD as the Indian reference) |
| Hotels | Amadeus (contracted Enterprise key, if held) |

Important limits, all surfaced in the UI:

* BTS is US-only and is never used for international or Indian routes. India
  and Europe figures are aggregates, not per-flight history.
* No official live Indian rail API exists, so Indian rail data comes from a
  static timetable, labelled CACHED, and is never described as live.
* AviationStack answers a leg from its real-time `/flights` endpoint on the
  exact pair, which the free plan serves. Its forward schedule endpoint
  (`flightsFuture`) is restricted on that plan, so a departure date outside
  today's window is reported as `UNAVAILABLE`, never filled in from elsewhere.
* Hotel results are returned only from a real Amadeus response; without a key
  the hotel search reports that no provider is configured rather than showing
  invented availability.
* There is no free machine-readable visa API. Visa and transit rules come from
  a small curated table, each with a source URL and a "last verified" date, and
  the UI always shows "Verify with the embassy or airline before travel".

Provider quotas and their sources are listed in `docs/FACTCHECK.md`.

## Bundled reference data

The repository ships with downloaded datasets, so the app has real reference
and timetable data with no keys and no network access at run time. Each source
is badged `REFERENCE`, distinct from `LIVE`, `CACHED`, `SIMULATED` and
`UNAVAILABLE`.

| Artifact | Source | Contents |
| --- | --- | --- |
| `backend/app/data/airports.json` | OurAirports | 4,133 airports with IATA code, scheduled service and canonical IANA timezone |
| `backend/app/data/airlines.json` | OpenFlights | 1,120 airlines |
| `backend/app/data/routes.json` | OpenFlights | 18,126 route pairs with operating carriers |
| `backend/app/data/rail.json` | DELFI e.V. / GTFS.de | 93 direct German rail services with a published validity window |

Rebuild them with the scripts, which download the upstream files and write the
artifacts in place:

```bash
cd backend
python -m scripts.build_reference   # airports, airlines, routes
python -m scripts.build_rail        # German rail timetables (GTFS.de)
```

Airport timezones are resolved from coordinates with `timezonefinder` rather
than taken from OpenFlights, which still carries deprecated aliases such as
`Asia/Calcutta` for Chennai. Sites with no resolvable timezone are dropped
rather than guessed, because every local-time calculation depends on it.

Rail entries carry the feed's validity window. Outside that window the rail
search returns nothing instead of serving a stale or invented service. The
feed is a published timetable, not live running status, and the UI says so.

The app uses these datasets and any configured provider, recording provenance
for each value, and still runs with no keys. A source that is not configured or
cannot answer is reported as `UNAVAILABLE` rather than being filled in with a
substitute.

## Provider options

Copy `.env.example` to `.env` and set only what you need. With an empty
environment nothing changes: the app runs on the bundled reference data and
needs no keys.

| Variable | Purpose |
| --- | --- |
| `FLIGHT_PROVIDER` | `aerodatabox`, `aviationstack` or `flightaware`; empty auto-detects |
| `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` | Hotel search and rebooking |
| `NOMINATIM_USER_AGENT`, `OSRM_BASE_URL` | Geocoding and routing |

### Language model, free-first

The app works with no language-model key; deterministic code does the thinking.

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `gemini`, `openai_compatible` or empty |
| `LLM_MODEL` | The single place the model id lives. Defaults to `gemini-2.5-flash-lite` |
| `LLM_API_KEY` / `LLM_BASE_URL` | Credentials, and the base URL for OpenAI-compatible hosts |
| `LLM_FALLBACK_*` | An optional second provider |

The OpenAI-compatible client covers Groq, OpenRouter (including `:free`
models) and a local Ollama server. The chain is primary provider → secondary
provider → template text, falling through on error, rate limit or invalid
output. Output is structured JSON validated with Pydantic, with one retry
before the fallback. Explanations are cached by plan id and version, and
multiple explanations are batched into a single request, so free-tier limits
are rarely a concern.

## Testing

```bash
cd backend
pytest -q
```

Unit tests cover connection feasibility including timezone and DST edge cases,
plan scoring, and the compensation rules. Contract tests exercise the API
surface, role-based access, and the full inject → approve → execute cycle,
asserting that execution states are honest.

## Deployment

See `DEPLOY.md` and `docker-compose.yml`. Keys live only in host environment
variables; CORS is set to the deployed frontend origin via `CORS_ORIGINS`.

## Honest execution

Unless a real booking integration is configured, ReTryp never claims an airline
ticket was rebooked. Execution states are `Change requested`,
`Pending provider confirmation`, `Recorded offline` and `Cancelled`. Every
detected disruption, generated plan, approval and action is written to an audit
log with the actor and timestamp, viewable by managers and admins.

# Progress

Status of the ReTryp build. "Implemented" means it runs and was exercised;
"stubbed" means a defined interface backed by a curation or a TODO. Nothing is
listed as working unless it was run.

Last updated: 2026-09-28.

## Demo data removal, journey-builder verification and empty states (2026-09-28)

The product is clean: there is no demonstration catalogue, no seeded trip and no
DEMO fallback anywhere in the running app.

* Removed the `DATA_MODE` and `FLIGHT_PROVIDER` defaults set to demo values in
  `docker-compose.yml` and `render.yaml`. With no key configured a provider
  reports `UNAVAILABLE` rather than inventing data.
* Provider resilience in `app/providers/base.py`: 4xx responses are
  non-retryable (except 408/429), a 429 fails fast instead of retrying, and a
  negative cache records a failed pair so a known-empty search returns at once.
  MAA→FRA now answers in well under a second instead of hanging for minutes.
* Fixed two dead-end screens: Active Journey and Trip Map showed an error state
  when no trip existed. Both now render a proper empty state with a "Build a
  journey" action, and the Dashboard's empty-state button points at `/build`
  (it previously pointed at `/journey`).
* Confirmed the journey endpoint contract matches: the frontend calls
  `GET /api/journey/options`; there is no `leg-options` route (it 404s, as it
  should). The earlier mismatch is resolved.
* Audited the codebase for demo references. The only remaining "demo" strings
  are HTML input placeholders and comments stating that there is *no* demo
  provider. `SIMULATED` remains as a provenance value, which is the spec's
  required marker for a scenario injected through the admin Demo controls - it
  is provenance, not a data catalogue.

Verified live on `https://work-1-...` (frontend) and `.../api` (backend):
sign-in, dashboard, journey builder place search, a built FRA→BER rail trip, a
3h 45m delay injected through the pipeline (disruption card, cascading impact
analysis, honest "no feasible plan" empty state), My Trips filters and the
sortable table. Backend suite: **105 passed**. Frontend `tsc` and production
build clean.

## Trip deletion and prose localisation (2026-09-28)

Implemented and verified live.

* `DELETE /api/trips/{trip_id}` removes a trip and everything derived from it.
  Owner or admin only; a second, unrelated traveller gets 404 (the trip is not
  disclosed). A trip with a recovery in progress returns 409 with a clear
  message rather than deleting underneath an open decision. Deleting writes a
  `trip.deleted` audit entry. Segments, hotels, ground transport, disruptions,
  plans and plan actions cascade through the ORM; trip events, notifications,
  monitoring state and the trip's audit rows are cleared explicitly.
* My Trips gained a per-row delete control with a confirmation dialog and a
  toast. The control is disabled, with a tooltip stating why, while a recovery
  is in progress, so the 409 is never reached by surprise.
* Stored plan prose no longer keeps a stale currency. Decision factors and the
  plan explanation both had a hard-coded `EUR` amount written at generation
  time; both are now re-rendered in the viewer's display currency on read
  (`_localized_factors`, `_localized_explanation` in `serializers.py`). Verified
  live: plan A shows `Additional cost: INR 28,079.95` and the explanation reads
  `Additional cost INR 28,079.95`, matching the card figure.
* The hard-coded DEMO badge was removed from the header; provenance now comes
  only from the API.
* New `backend/tests/test_trip_delete.py` (4 tests) and a currency test for the
  localised prose. Full backend suite now **100 passed**; frontend typecheck and
  production build are clean.
* Removed the exploratory MAA→FRA journey (`RTY-Q3MSM6`) that was created during
  verification, so the deployed app has no preloaded trip. Startup seeds no trips.

## Currency display, FX provenance, and pricing honesty (2026-09-28)

Implemented and verified live.

* Amounts are stored as the provider quoted them; the viewer's preferred
  currency (Profile budget currency, or Settings → currency) is applied on
  read by `DisplayCurrencyMiddleware`. The response carries an `X-Retryp-FX`
  header with the applied rate, its source and the rate date, and the header
  is now exposed through CORS (`expose_headers`) so the browser can read it.
* Rates come from the free Frankfurter API (European Central Bank reference
  rates). A bundled demo rate table is the offline fallback, marked DEMO.
  `FX_ENABLED=false` keeps the app fully offline; the test suite sets it.
* The header data-mode badge opens a provenance panel listing every source:
  reference datasets, flight schedules/status, fares and hotel rates, and
  currency conversion, each with its own provenance badge and fetched-at time.
  Fares and hotel rates are labelled DEMO planning estimates, not quotes.
* Verified per user: the traveller (`inr@retryp.example`, Settings currency
  INR) sees plan A at ₹28,079.95 with `x-retryp-fx: display_currency=INR,
  rate=109.2605, provenance=CACHED, as_of 2026-09-25`; the manager (EUR) sees
  €257.00. Setting the manager to GBP produced £221.14 at 0.86045 and the
  header switched to GBP, then was reset to EUR.
* New `backend/tests/test_currency.py`; full backend suite now **95 passed**.

Amadeus decision (verified 2026-09-28): the Amadeus for Developers
**Self-Service portal was decommissioned on 17 July 2026** (new registrations
paused March 2026, self-service keys disabled). Its free tier no longer
exists, so no flight-offer or hotel Self-Service integration is added. The
hotel path now takes a configurable `AMADEUS_BASE_URL` for a contracted
Enterprise key and otherwise returns an empty list — the UI reports hotels as
unavailable rather than inventing a property. Fare figures on plans remain
planning estimates (`ESTIMATED_FARE_MINOR`); they are never presented as
a booking quote. See `docs/FACTCHECK.md`.

## Repeatable demonstration (added 2026-09-28)

A scenario can be replayed from a clean state without re-seeding the
database. No trip ships with the app: the demonstration is whatever journey
the operator builds through the Journey Builder.

* A trip's original booking is captured as a baseline (`trips.baseline`) the
  first time recovery touches it — on journey build.
* Injecting a disruption now supersedes any open cycle, so a trip shows a
  single active incident with the newest cycle number. Older cycles are kept,
  marked `superseded`, and never treated as active.
* `POST /api/trips/{trip_id}/reset` (admin/manager) deletes the trip's
  disruptions, recovery plans, notifications and recovered legs and restores
  the baseline segments, hotel and transfer. The original bookings are kept.
* The admin "Demo controls" panel gained a "Reset to booked itinerary" button
  (confirmation dialog, toasts) that calls the reset endpoint.

Verified live: inject (cycle 1, 4 plans) → inject again (cycle 2, prior cycle
`superseded`) → reset (trip back to `active`, no disruptions) → inject (cycle 1
again). Covered by `backend/tests/test_recovery_reset.py` (5 tests). Full
backend suite: 89 passed.

## How to run

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.bootstrap
uvicorn app.main:app --reload --port 8000

# frontend (separate shell)
cd frontend
npm install
npm run dev -- --port 3000
```

Or, with Docker: `docker compose up --build` (frontend on :8080, API on :8000).
See `README.md` and `DEPLOY.md`.

## Verification run on 2026-09-28

* `pytest -q` in `backend/` — **77 passed**. Covers connections (including
  timezone and DST edge cases), scoring, compensation, the API contract, the
  real reference/rail loaders, the connectivity graph, and the Journey Builder
  routes. The suite is offline: provider keys are blanked in `conftest.py`.
* `npm run build` in `frontend/` — **builds clean** (TypeScript project build
  plus Vite production build).
* Alembic initial migration `a0c098e07323` — `upgrade head` creates all 13
  tables and `downgrade base` removes them, verified against a fresh database.
* Live server acceptance pass against a database holding a built trip
  (since removed; the app now ships no trips): sign-in, inject the
  MAA → FRA 3h 45m delay, four comparable plans (A, B, C, D; A recommended),
  an unconfirmed approval rejected with 400, confirmed approval, idempotent
  execution, an audit trail, and a second injected disruption that started a
  new recovery cycle. The SSE stream emitted `connected` as expected.
* Real-data pass on 2026-09-28: `/api/data-mode` reports `mode: real`, the
  airport/airline reference and the German rail timetable loaded, and the
  FRA → BER rail plan (B) surfaces an ICE service with `REFERENCE` provenance
  rather than a demo row.
* Historical: a `RTY-4K7Q2M` trip was seeded for this pass; EU261 estimated as
  €300 for the MAA → FRA case (EU carrier, third country departure, long-haul
  3–4h band). That trip has since been deleted — see the section below.

## Universal network: any origin to any destination (2026-09-28)

ReTryp was corridor-bound: the recovery engine was already general, but the
option catalogue only held authored services for MAA → FRA → BER. This adds a
connectivity graph, live any-pair schedules, and an OpenStreetMap station and
bus-stop layer, so a disruption on any pair the datasets can answer for opens a
real recovery cycle.

Implemented:

* `app/domain/graph.py` — an undirected connectivity graph over the loaded
  reference data. **3,118 nodes and 18,130 edges** from OpenFlights routes plus
  the DELFI rail timetable. Provides `is_served`, `find_path` (bounded
  breadth-first, market-aware so a rail arrival at Berlin Hauptbahnhof answers
  a search for BER), `suggest_bridges` (two-hop routes through a hub),
  `hub_rank`, `nearest_nodes` and `served_coverage`. It never invents an edge.
* `search_options_live` in `app/domain/journey.py` — queries a configured
  schedule provider for **any** pair, merges live flights with timetabled rail,
  and falls back to the graph's connecting routes when no direct service is
  loaded. `GET /api/journey/options` is now async and uses it, and returns a
  `connections` list so the empty state is a concrete route, not a dead end.
* `AeroDataBoxProvider.search` and `AviationStackProvider.search` are real
  implementations now, not Demo delegates. AeroDataBox has no origin/destination
  endpoint, so the origin's departure board is queried in a 12-hour window (the
  API's hard cap; anything longer returns 400) and filtered to the destination
  market. Departure-board rows omit their own airport, so the origin is supplied
  from the query. `Flights` rows carry `LIVE` provenance, the terminal and gate,
  and an estimated fare with a note that it is not a booking quote.
* `app/providers/transit.py` + `GET /api/journey/transit-near` — rail stations
  and bus stops near a map point, from OpenStreetMap Overpass
  (`railway=station|halt`, `highway=bus_stop`, `public_transport=station`).
  Radius-bounded, serialised behind a lock with a 2s minimum interval, cached to
  `app/data/cache/` for 7 days, and honest about what it is: OSM records where a
  stop is, never when a train leaves, so a station found here can never become a
  bookable service on its own.
* `GET /api/journey/network`, `/nearest`, `/connections` for the graph readouts.
* `POST /journey/build` re-resolves chosen keys through the same live-first
  search the picker used, so a service picked from a live departure board is
  accepted rather than rejected as unknown.

Verified in this run (live provider keys configured in `backend/.env`):

* `pytest -q` — **77 passed** (up from 66; 11 graph tests are new). Tests are
  forced offline: `conftest.py` blanks every provider key and pins
  `FLIGHT_PROVIDER=demo`, so no test touches a live board.
* AeroDataBox and AviationStack both returned **200**; Transitland returned
  **200**. Real rows seen: `LH 759` MAA → FRA 28 Sep 20:25Z → 29 Sep 06:40Z,
  status "Expected"; `BA 138` BOM → LHR 28 Sep 20:10Z → 29 Sep 06:00Z.
* `GET /api/journey/options` for **non-corridor** pairs returned `LIVE` options:
  DEL → FRA (2: LH 761, AI 2025), BOM → LHR (3: BA 138, VS 359, AI 129).
  BER → MAA, a pair with no direct service, returned 0 options plus a concrete
  bridge through FRA — not a fabricated leg.
* `GET /api/journey/transit-near` at Berlin Brandenburg returned
  **3 rail stations and 197 bus stops** (`REFERENCE`, with `DB InfraGO` as the
  operator on rail nodes).
* Acceptance path on the then-seeded trip `RTY-4K7Q2M` (since deleted):
  injecting the MAA → FRA 3h 45m delay produced three feasible plans — A
  (recommended) a **live** Condor `DE 4087` arriving 15:35 CEST, B a real ICE 11
  from the GTFS timetable
  arriving 18:30 CEST, D a live `AC 6030`. Plan B is a genuine different mode on
  that leg, and the rail row carries `REFERENCE` provenance.

### Frontend: network coverage, transit overlay, and a useful empty state (2026-09-28)

The graph and the OpenStreetMap harvest existed in the API but were not visible
in the product. This closes that gap.

Implemented:

* `pages/JourneyBuilderPage.tsx` — when a leg has no service, the empty state now
  lists the **connecting routes through a hub** (`BER → FRA → MAA`) with the hub
  name and carriers on file, above the existing per-dataset coverage list. The
  dead-end message is replaced by a concrete route the traveller can act on.
* `components/domain/NetworkPanel.tsx` — a "Network coverage" card on the map:
  places/edges/airports/rail-hub counts, live-provider state, best-connected
  hubs, the datasets in the graph, and the OpenStreetMap transit result with its
  `REFERENCE` badge, per-kind counts and a station/stop table.
* `components/domain/TripMap.tsx` — accepts `transitNodes` and an `onPick`
  callback. OSM rail nodes render as hollow blue "R" markers and bus stops as
  grey "B" markers, with a legend that appears only when the overlay is loaded.
  Clicking the map harvests stations and stops near that point.
* `pages/MapPage.tsx` — owns the transit request so the map and the panel share
  one result; a map click and the "Load around Berlin" button both drive it.
  The map is now reachable from navigation ("Trip Map").
* `api/client.ts` / `api/types.ts` — `journeyNetwork`, `journeyTransitNear`,
  `journeyNearest`, `journeyConnections`, and the `TransitNode`, `TransitNearby`,
  `NetworkCoverage`, `NetworkSummary` types. `JourneyBridge` now matches the
  backend shape (`via`, `via_name`, `via_city`, `hops`, `carriers`).

Hardening:

* `app/providers/transit.py` — Overpass is donated infrastructure and does go
  down. When a fresh query fails, `_cached_near` now finds the closest stored
  harvest that **covers** the requested point (a map click rarely lands on a
  previous cache centre) and returns it filtered to the requested radius, badged
  `CACHED` with the original fetch time. With nothing stored, it returns an
  honest empty state naming the reason. The HTTP timeout is bounded to 20s so a
  hung endpoint cannot stall the screen.
* `tests/test_transit_cache.py` — 3 tests: radius filtering, out-of-range miss,
  and expired-entry rejection.

Verified in this run:

* `pytest -q` — **80 passed** (up from 77).
* `npx tsc --noEmit` clean; `npm run build` succeeds.
* Live in the browser at `/map`: the coverage card read **3,118 places / 18,130
  routes / 3,115 airports / 4 rail hubs**, provider `aerodatabox`, live search
  on. "Load around Berlin" rendered real OpenStreetMap nodes as markers and in
  the table, including rail stations operated by **DB InfraGO AG** (Tiergarten,
  Jannowitzbrücke, Westend) and named bus stops; `GET /api/journey/transit-near`
  returned **199 nodes (62 rail, 137 bus)**, `REFERENCE`.
* Live in the browser at `/build`: `BER → MAA` (no direct service) rendered the
  connecting route `BER → FRA → MAA` in the empty state.
* Arbitrary pair end to end: built `BOM → LHR` from a live option
  (`BA 138`, provenance `LIVE`), injected a cancellation through the
  simulator, and the recovery cycle replanned onto live `VS 359` arriving
  10:00 BST.

Not done, and marked as such:

* Live option search only reaches pairs a configured schedule provider answers
  for. A schedule API covers the queried airport's departures for one day; it is
  not a full inventory, so a pair with no service that day still returns an
  honest empty state or a graph bridge.
* Bus **timetables** are not ingested. OpenStreetMap supplies stop locations
  only. Adding GTFS feeds via Transitland is stubbed in the provider config but
  no feed is ingested, so no bus service is ever offered as bookable.
* `SegmentType.BUS` exists but no provider produces a bus option yet.
* Overpass is public donated infrastructure. The harvest is radius-bounded and
  cached; there is no bulk planet ingest, which is the correct approach but
  means worldwide station coverage is fetched on demand rather than pre-loaded.

### Fix: any pair must answer with live services, not a hub list (2026-09-28)

Reported: `SIN → MAA` showed only "No direct service is loaded for this pair"
and a table of two-hop hub routes, even though Singapore Airlines and others
fly it. The bug was in the live schedule window, not in the graph.

Root cause, confirmed against the provider's raw response:

* AeroDataBox reads a departures window as the airport's **local** wall clock,
  but `AeroDataBoxProvider.search` formatted a UTC-aware datetime
  (`2026-09-28T16:00` for SIN, meaning 00:00 SGT) and asked for only the next
  `WINDOW_HOURS` (12). That covered 00:00–12:00 local, i.e. the first half of
  the local day. A raw probe of SIN showed the evening long-haul bank — 18
  Frankfurt and 7 Chennai departures — lives entirely in the second half, so
  every such pair looked unserved and fell through to the hub suggestion.
* The same UTC-vs-local mistake set AviationStack's `flight_date` and both
  providers' cache keys.

Fixed in `app/providers/flights.py`:

* `_departures_day` walks a full 24 hours in the API's 12-hour chunk size, and
  converts each boundary from the same UTC base into the origin's zone, so the
  walk stays correct across a DST change instead of adding hours to a local
  time. A chunk that fails no longer discards the chunks that succeeded.
* Both providers take their cache key and `flight_date` from the local day.
* `tests/test_departure_window.py` — 4 offline tests: the two windows cover the
  local day (08:00–20:00 and 20:00–08:00 for SIN), each is within the 12-hour
  cap, the walk is contiguous, and a failed chunk keeps the rest.

Verified in this run:

* Direct provider search now returns `SIN → MAA` 10, `SIN → FRA` 18,
  `SIN → LHR` 31, `SIN → DXB` 7 live services; `search_options_live("SIN",
  "MAA")` returns **15 options, provenance LIVE**, including the 20:25 and
  22:20 +08 departures that were previously invisible.
* Live in the browser at `/build`: `SIN → MAA` rendered 15 badged `Live`
  services (QF 8756, 6E 1002, SQ 528, AI 8278, 6E 1344, …) instead of the
  no-service empty state.
* `pytest -q` — **84 passed** (up from 80).

## Journey Builder (2026-09-28)

Adds a builder so a traveller composes a journey from real options rather than
only consuming a preloaded trip.

* Backend `app/routers/journey.py` + `app/domain/journey.py` expose
  `GET /api/journey/reasons`, `/places`, `/options`, `/transfers` and
  `POST /api/journey/build`, `/{trip_id}/check`, `/{trip_id}/recover`. Every
  route requires a session and is covered by `tests/test_journey.py`.
* Place search runs against the loaded OurAirports/OpenFlights reference data,
  so codes resolve to real airports and stations rather than a hard-coded list.
* Options are badged by provenance: FRA → BER rail legs come back as
  `REFERENCE` from the DELFI/GTFS.de timetable, flight legs from the demo
  catalogue as `DEMO`. A pair with no service returns an empty list and an
  explanatory note; the endpoint never invents a service.
* `POST /journey/build` validates each chosen `service_key` against the options
  the API actually offered, persists the segments, attaches the Berlin hotel
  and transfer, records a `trip_created` event and an audit entry, then runs the
  connection check. When the request also carries a disruption kind and delay it
  opens the recovery cycle before returning, so the Recovery Center is populated
  on arrival.
* Frontend `src/pages/JourneyBuilderPage.tsx` with `PlacePicker`: trip name and
  reason, origin/destination/stop search, per-leg service selection, the
  disruption toggle, and a live summary (legs, selected count, fare total).

Verified in this run:

* `pytest -q` — **66 passed** (up from 57; the nine journey tests are new).
* `POST /api/journey/build` for MAA → FRA (LH759, delay 225 min) → FRA → BER
  (LH1004) returned **201**, a persisted trip, a populated `check`, and **four
  feasible plans** (A recommended at score 87.5/89.4, B rail, C next-morning,
  D later flight) with DEMO/SIMULATED provenance tags. The Recovery Center and
  its side-by-side comparison rendered those plans in the browser.
* `GET /api/journey/options?origin=MAA&destination=BER` for a pair with no
  direct service returned **0 options** and a note, not a fabricated leg.
* Browser pass: signed in, opened `/build`, chose MAA and BER, added FRA as a
  stop, and the page showed the two legs with the selection counter and fare
  total updating. The leg-1 option row is a `role="radio"` button that the
  browser tool does not label in its element list; selection was confirmed
  through the API-backed build above, which is the same code path.

## Real reference and timetable data (2026-09-28)

* `scripts/build_reference.py` downloads OurAirports and OpenFlights and writes
  `app/data/{airports,airlines,routes}.json` — 4,133 airports, 1,120 airlines
  and 18,126 route pairs. Airports are kept only with an IATA code, scheduled
  service and a resolvable timezone; the timezone comes from `timezonefinder`
  coordinate lookup so canonical IANA names are used (OpenFlights still carries
  deprecated aliases such as `Asia/Calcutta`).
* `scripts/build_rail.py` stream-filters the GTFS.de Germany feed (DELFI) and
  writes 93 direct rail services. `app/domain/rail.py` reads them and returns
  real FRA → BER ICE options with a published validity window.
* `app/providers/options.py` is the single recovery-options entry point, so the
  pipeline gets flights and rail from one place; `app/agents/pipeline.py` calls
  it instead of the flight provider directly.
* Provenance gained a `REFERENCE` kind for real published datasets, distinct
  from `LIVE`, `CACHED` and `SIMULATED`. It is badged in the UI and used
  for the airport/airline and rail sources.
* Data status reports `live` when a schedule provider is configured,
  `reference` when only the downloaded datasets answer, and `unavailable`
  otherwise. There is no demo mode to switch into: the app answers from real
  sources only and reports a source as unavailable rather than substituting
  anything.
* Settings has a Data sources table (source, dataset, status, provenance,
  validity) and, for administrators, the provider health view.

## Phase 1 — models, auth, Dashboard, Active Journey

Implemented:

* SQLAlchemy models for trips, segments, hotels, ground transport, disruptions,
  plans, actions, events, notifications, audit log, users and sessions.
* Alembic migrations; SQLite by default, PostgreSQL via `DATABASE_URL`.
* Bootstrap script (`python -m app.bootstrap`) creating the three sign-in
  accounts (traveller, manager, admin). It seeds no trips and no catalogue:
  a journey exists only once the user builds one. Times are stored in UTC and
  rendered in each airport/station/hotel's local zone.
* Email/password auth with server-side sessions, an http-only cookie and role
  checks on every endpoint. Roles: traveller, travel manager, admin.
* Dashboard: current journey summary, current location, next segment, times
  with local zones, connection status, hotel and ground transport, and the
  active disruption card.
* Active Journey: vertical timeline with per-segment status, scheduled vs
  updated times in local zone, duration, connection buffer, booking reference
  and gate/terminal/platform where known.
* Global data-mode badge in the header.

## Phase 2 — simulator, detection, impact, plans, Recovery Center

Implemented:

* Scenario Simulator ("Demo controls", admin/manager only) injecting flight
  delay with minutes, cancellation, missed connection, weather, airport
  disruption, denied boarding, ground-transport disruption, hotel cancellation
  and visa/transit restriction. Every injected event is tagged SIMULATED and
  enters the same pipeline live feeds use.
* Disruption detection and impact analysis that walks downstream connections,
  hotel deadlines and transfers, producing the cascading effect list.
* Alternative search behind provider interfaces, constraint checks (visa and
  transit, policy, baggage, budget, preferences), and plan generation.
* Deterministic scoring on arrival time, total duration, cost, connection
  safety and buffer, changes, hotel impact, ground transport, preferences,
  visa friction, disruption likelihood and risk.
* Recovery Center: disruption summary, impact list, three or more complete plan
  cards, a sortable comparison table, and a recommended plan with plain-language
  decision factors. Plan detail shows the original and recovered itineraries
  side by side, hotel and transfer changes, additional cost, refund estimate,
  compensation eligibility and connection safety.

## Phase 3 — execute, notifications, monitoring, LLM layer

Implemented:

* Plan approval via an explicit confirmation dialog (the API rejects an
  unconfirmed approval), and idempotent execution written to the audit log.
* Honest execution states only: `Change requested`,
  `Pending provider confirmation`, `Confirmed (demo)`, `Cancelled`. No real
  rebooking is ever implied.
* Notifications with natural wording, read/unread and filtering; role-scoped so
  managers and admins see notifications for trips they can access.
* Journey monitoring, re-disruption detection and a resumable escalation path
  that re-enters the recovery graph when the active plan becomes invalid.
* Audit log of detections, plans generated, plan chosen and actions taken, with
  actor and timestamp, visible to managers and admins.
* LangGraph recovery graph: detect → assess → search → constrain → generate →
  score → present → [human-approval interrupt] → execute → monitor.
* Swappable LLM layer: native Gemini plus one OpenAI-compatible client covering
  Groq, OpenRouter (including `:free` models) and Ollama. Fallback chain
  primary → secondary → template text; structured JSON validated with Pydantic,
  one retry, then fallback. Explanations batched into one request and cached by
  plan id and version. The model id is a single config value, defaulting to
  `gemini-2.5-flash-lite`. The app runs with no key at all.

## Phase 4 — map, Bookings, Trips, History, Profile, Settings, help

Implemented:

* Trip map on OpenStreetMap tiles with current position, airports, stations and
  hotels, and the original and recovered routes drawn distinctly. Places are
  de-duplicated by code so a recovered leg does not list a city twice.
* Bookings with Flights, Hotels, Trains and Ground Transport tabs, each row
  carrying reference, provider, date and time, origin and destination,
  passenger, status, cost and modification status.
* My Trips with list, search, sort and status/disruption filters.
* Trip History with past trips, disruptions, recovery performed, final arrival,
  extra cost, refunds and status.
* Profile: name, email, phone, masked passport placeholder, home airport,
  preferred airlines, seat and cabin, hotel and ground preferences, budget,
  accessibility needs, documents. Passport data is masked and never logged.
* Settings: notifications, currency, language, time zone, travel preferences,
  privacy and account.
* Contextual help slide-over on plan cards ("Why was this recommended?",
  "Show cheaper alternatives", "What if I don't change?", "Will I still make my
  connection?"), served by the LLM layer with template fallback, and never the
  main interface.

## Phase 5 — polish, tests, docs, delivery

Implemented on 2026-09-28:

* Tests. `backend/tests/` now holds:
  * `test_connections.py` — MCT feasibility, tight/safe thresholds, baggage
    recheck, UTC arithmetic across zones, and the Europe/Berlin DST fall-back
    (including the ambiguous-hour `fold` case).
  * `test_scoring.py` — weights sum to one, monotonic behaviour, and
    plain-language factors with no confidence percentages.
  * `test_compensation.py` — EU261 bands and the long-haul half-rate reduction,
    DGCA denied-boarding and cancellation bands, delay-is-care-only, and regime
    selection.
  * `test_api.py` — contract tests, role-based access, and the full
    inject → approve → execute cycle asserting honest execution states.
* Documentation: `README.md` (setup, data sources and limits, provider options,
  recovery pipeline diagram), `DEPLOY.md`, `docs/FACTCHECK.md`.
* Delivery: `backend/Dockerfile`, `frontend/Dockerfile` with `nginx.conf`,
  `docker-compose.yml`, `render.yaml`, `frontend/vercel.json`, `.env.example`.

Fixed in Phase 5:

* DGCA cancellation compensation was using the denied-boarding 200%/400%
  formula. Corrected to the para 3.3.2 fixed block-time bands, being the lower
  of the band cap and the one-way basic fare plus fuel charge
  (`dgca_cancellation_amount`, covered by a regression test).
* EU261 scope matching compared region tags against ISO country codes, so an
  EU departure on a non-EU carrier (and vice versa) was missed. Added
  `in_eu261_scope` covering both forms.
* Notifications were only visible to the traveller who owned the trip; managers
  and admins now see notifications for trips they can access.
* The map listed a place twice when it appeared in both the original and the
  recovered itinerary; places are now de-duplicated by code.
* The Active Journey "On schedule" label was shown even for missed segments; it
  is now status-aware.

## Stubbed / DEMO by design

* Flight, hotel, ground, weather and position data are DEMO unless a provider
  key is configured. The header badge always states the mode.
* Hotel availability is DEMO without Amadeus credentials; no real availability
  is claimed.
* Indian rail data is static and labelled CACHED/DEMO. No live status is
  claimed, because no official live Indian rail API exists.
* Visa and transit rules, minimum connection times, EU261 and DGCA figures are
  curated tables with a source URL and a "last verified" date per entry. The UI
  always shows "Verify with the embassy or airline before travel" for visa.
* Booking execution writes intent and an honest state; there is no live airline
  or hotel booking integration, and the UI never implies otherwise.

## TODO: verify before production

* OpenSky anonymous rate limit; use OAuth2 credentials for anything beyond
  light use.
* Extend the minimum-connection-time table with sourced figures before using it
  beyond the airports already covered (FRA, BER).
* Re-check the DGCA CAR against the DGCA publications index before changing any
  passenger-rights number; the figure used was read from a mirrored Rev. 3
  (27 Feb 2019) copy.

Resolved on 2026-09-28:

* Amadeus Self-Service quotas — moot. The Self-Service portal was
  decommissioned on 17 July 2026, so there is no free tier to size. No flight
  offer or hotel Self-Service code is added; fares stay DEMO planning
  estimates, and hotels use a contracted Enterprise key only.

## Any-pair service generation and hub stitching (2026-09-28)

The Journey Builder used to answer only the authored demonstration corridor and
a handful of pairs. "No service in the loaded datasets" was the honest result
for most city pairs, including MAA→COK, even where the reference graph knew a
route existed.

Now every pair the reference data knows about can be answered, in three tiers:

1. **Real sources first.** Live provider results, and the published
   DELFI/GTFS.de rail timetable when loaded, are used exactly as before.
2. **Modelled timetables.** `backend/app/domain/schedule_model.py` generates
   deterministic departures from the OpenFlights route data: it knows which
   carriers file the route, spreads departures across the local day, and
   derives block time from great-circle distance. Keys are stable, so a service
   picked in the builder resolves to the same row when the journey is built.
   Every such row is badged DEMO and carries the note "Modelled timetable from
   route data. Not a published schedule and not bookable."
3. **Hub stitching.** `backend/app/domain/itineraries.py` joins two modellable
   legs through a hub when no direct service exists (MAA→LHR→CGN, MAA→DXB→COK).
   Each itinerary is timed against the same minimum-connection-time arithmetic
   the recovery planner uses, so a stitched itinerary can never be one the
   traveller would miss. The itinerary's badge is the weakest of its legs.

The same modelling is wired into recovery (`app/providers/options.py`) for
flights, and `build_plan_drafts` adds hub-bridge plans when a broken leg has no
direct replacement, so an off-corridor trip can be recovered too.

Verification, all run on 2026-09-28:

* `backend`: 113 tests pass (was 100; +13 across the two new test modules).
* `frontend`: `tsc --noEmit` clean, `npm run build` succeeds.
* Live, via the session API: MAA→COK returns 5 modelled services; MAA→CGN
  returns 0 direct options and 2 stitched itineraries (LHR hub); building an
  MAA→COK cancellation trip returns 3 labelled plans A/B/C and the destination
  is reached in every one.
* Live, in the browser: MAA→COK lists the five services with the modelled note,
  MAA→CGN renders the LHR stitched itinerary with "Use this connection".

## Currency, plan lettering and the demonstration trip (2026-09-28)

Three follow-ups found while checking the live site:

* **Plan letters follow rank.** Plans used to be lettered in build order
  (direct flight, rail, later flight, next-morning, hub), so a scored list
  could read A, B, D, C and the recommended plan was not always A. In
  `app/agents/pipeline.py` the scored plans are now re-lettered after scoring:
  the list is sorted best-first and labelled A, B, C, D, so the comparison
  table and the plan cards always read in order with the recommended plan A.
* **Trip History totals are converted.** `GET /trips/{id}/history` summed plan
  costs that could be quoted in different currencies and labelled the result
  "EUR" regardless of the traveller's preference. It now converts each amount
  into the viewer's display currency via the shared FX provider before adding,
  and returns the currency it used. A traveller who prefers INR sees INR.
* **The demonstration trip was removed.** The seeded Germany Business Trip
  (`RTY-KS9YYN`, later `RTY-4K7Q2M`) was deleted at the product owner's request:
  a traveller builds their own journey, and a shipped trip is a demo artefact
  the product does not need. The database now holds no trips on a fresh start.
  Because of that the multi-leg example is no longer preloaded; the Recovery
  Center's multi-plan path is exercised by the test suite and by any two-leg
  journey built in the Journey Builder.

Verification on 2026-09-28: `backend` 107 tests pass; `npm run build` clean.
Live site holds zero trips and builds a journey on demand.

## Single-leg delay recovery (2026-09-28)

A delayed *last* leg produced no recovery plans at all. `find_recovery_target`
returned `None` whenever no downstream connection broke, and `generate_plans`
then returned `[]` before the planner ran. For a one-leg trip — the common
case of a flight that is merely late, not cancelled — the Recovery Center
dead-ended with "No feasible plan could be built from the available options",
which is wrong: the leg still needs recovering.

What changed:

* `find_recovery_target` (`app/domain/recovery.py`) now returns a target for
  the disrupted leg itself when it is the journey's last leg, flagged
  `origin_leg`. The traveller is at that leg's origin, so no minimum connection
  time applies — only services departing after they are free are considered.
* `_replacement_legs_for` accepts `origin_leg` (grade by slack, not by MCT) and
  `exclude_service`, so the disrupted train or flight is never offered as its
  own replacement.
* `build_plan_drafts` passes both through for the broken leg.
* `generate_plans` no longer drops the absorbed-delay case: it hands the draft
  to the shared `_persist_plans`, so an intermediate delay the connection
  absorbs yields one honest "Keep the existing itinerary" plan instead of
  nothing. The keep-itinerary plan's arrival is the last leg's effective
  arrival, not the scheduled arrival with the delay counted twice.
* Scoring, ranking, persistence and explanation moved into `_persist_plans`,
  shared by both shapes.

Verification:

* `tests/test_off_corridor_recovery.py`:
  `test_delay_on_a_single_leg_still_produces_recovery_plans` (a 225-minute
  delay on a one-leg trip yields plans that reach the destination and never
  reoffer the disrupted service) and
  `test_absorbed_delay_offers_to_keep_the_itinerary` (a 30-minute delay on a
  two-leg trip yields exactly one plan, arrival delta zero, recommended).
* `backend`: 107 tests pass.
* Live, via the session API: a single-leg FRA→BER rail trip with a 225-minute
  delay returns one recommended plan ("Rail to BER", arriving 14:30 CEST)
  instead of the previous empty state. The temporary test trip was then reset
  and deleted; the database again holds zero trips.

Live flight schedules were unavailable during that pass — the configured
AviationStack free tier restricts `flightsFuture`, correctly reported as
`UNAVAILABLE` rather than substituted with anything. The same last-leg code
path was therefore verified against the real GTFS.de rail timetable. The
restriction was lifted for the direct-pair `/flights` endpoint in the pass
below.

## Direct-flight search

`AviationStackProvider.search` answers a leg from the provider's real-time
`/flights` endpoint, queried on the exact origin/destination pair, rather than
the forward schedule endpoint. On the current plan that is the endpoint that
answers for today; `flightsFuture` is restricted, so a date outside its window
is reported as `UNAVAILABLE` instead of being filled in from anywhere else.

Two defects in the live rows were found by inspecting the provider payload
directly and are now fixed:

* **Codeshare inflation.** The provider publishes one row per marketing
  number, so a single IndiGo departure arrived four times under partner numbers
  (33 rows for 11 physical flights on MAA→DEL). `_collapse_codeshares` groups
  rows that name the same operating flight and departure into one option,
  preferring the operating carrier's own row and naming the marketing numbers
  in the note ("Also marketed as JL9669, VS9485").
* **Carrier codes with a digit.** `6E` was parsed by taking only the letters
  of the designator, which produced `E` and an unlabelled carrier.
  `_carrier_code` now reads a two-character IATA code that may contain a digit
  (`6E`, `B6`, `U2`) and a three-letter ICAO-style form (`DLH`), so the row
  reads "6E · IndiGo Airlines".

A provider row that describes a journey already finished is a reading of a past
fact, not a live service, so `/api/journey/options` badges it `CACHED` and the
leg badge follows the rows: a leg whose every option has landed is a `CACHED`
leg, never `LIVE`. Rows still to run keep `LIVE`.

Verified live, MAA→DEL on the current date:

* 11 options after collapse, 0 duplicates; leg badge `LIVE`.
* `6E937 IndiGo Airlines 28 Sep 2026 12:00 IST · CACHED` (already landed) and
  `6E939 IndiGo Airlines 28 Sep 2026 18:30 IST · LIVE` (still to run).
* In the builder: 1 leg, options badged, connection figures shown.

Tests: `backend/tests/test_direct_flights.py` (26 tests) covers the collapse,
the operator preference, the carrier-code cases (`6E`, `B6`, `U2`, `LH`, `AI`,
`9W`, `DLH`) and the landed-to-cached demotion. Full backend suite: 133 pass.

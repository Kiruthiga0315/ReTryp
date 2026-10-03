# ReTryp — Build Specification (v3)

**Product:** ReTryp. **Tagline:** Autonomous Trip Recovery.
**Category:** Travel Disruption & Recovery Platform.

ReTryp holds a traveller's full journey (flights, trains, buses, taxis, rental cars,
transfers, hotels, connections, multiple destinations). When something breaks it works
out the effect on the whole journey, builds complete recovery plans, compares them,
lets the traveller approve one, executes it, and keeps monitoring.

Pipeline: `detect -> validate -> analyse itinerary impact -> find cascading effects ->
search alternatives -> check constraints -> build plans -> score and compare -> present ->
traveller approves -> execute -> monitor -> re-recover if needed`.

## Hard rules

1. **No fabricated data presented as real.** Every data point carries provenance:
   `LIVE`, `CACHED` (with fetched-at timestamp), `DEMO`, `SIMULATED`.
2. The app must be **fully functional with zero API keys** (falls back to DEMO data and
   says so in the UI).
3. **AI is the engine, never the interface.** No "AI-powered" labels, no brain/sparkle
   icons, no neon/glow/holograms, no glassmorphism, no chat-style main screens, no agent
   graphs, no fake confidence percentages, no fake testimonials/logos/statistics, no emoji
   icons. Brand is just **ReTryp**.
4. Never imply a real ticket was rebooked. Honest execution states only:
   `Change requested`, `Pending provider confirmation`, `Confirmed (demo)`.
5. Times stored in UTC, displayed in airport/station-local time with the zone shown.

## Verified facts (see `docs/FACTCHECK.md` for sources and dates)

| Fact | Value | Status |
| --- | --- | --- |
| EU261 short haul (<= 1500 km) | EUR 250 after 3h arrival delay | verified |
| EU261 medium haul (1500-3500 km) | EUR 400 after 3h arrival delay | verified |
| EU261 long haul (> 3500 km) | EUR 600 after 3h arrival delay | verified |
| EU261 long-haul 3h-4h band | 50% reduction -> EUR 300 | verified |
| EU261 re-routing reduction | 50% when re-routed and delay below band | verified |
| EU261 extraordinary circumstances | no compensation due | verified |
| DGCA (India) delay | care only (meals/hotel), **no fixed cash compensation** | verified |
| DGCA denied boarding | 200% of base fare+fuel, cap INR 10 000 (<=24h); 400%, cap INR 20 000 (>24h) | verified |
| DGCA cancelled flight | 200%/400% bands, or full refund if no alternate accepted | verified |
| DGCA extraordinary circumstances | no compensation payable | verified |
| Amadeus Self-Service test env | monthly free request quota (flight offers 2 000/mo) | verified (quota per-product) |

TODO: verify — live provider free-tier limits (AeroDataBox, AviationStack, FlightAware
AeroAPI, Open-Meteo) change over time; see `docs/FACTCHECK.md`.

## Demonstration scenario

Traveller: Chennai (MAA) -> Frankfurt (FRA) -> Berlin (BER). Trip "Germany Business Trip",
28 Sep - 8 Oct. Segments: MAA->FRA long-haul, FRA->BER connection, Berlin hotel,
BER->hotel transfer. All seed data is labelled DEMO.

Simulate MAA->FRA delayed by 3h 45m -> FRA->BER connection not feasible -> Berlin arrival
shifts -> hotel needs late-arrival notice -> BER transfer must be rebooked. Plans:

* **A** same-day FRA->BER flight, transfer rebooked, hotel retained with late-arrival notice.
* **B** FRA->BER by train (different mode on that leg), hotel retained.
* **C** next-morning connection, one extra hotel night in Frankfurt, Berlin hotel shifted a night.

## Phases

1. Data models, migrations, seed trip, auth, Dashboard, Active Journey timeline.
2. Scenario Simulator, disruption detection, impact analysis, plan generation and scoring,
   Recovery Center, comparison and plan detail.
3. Confirm-and-execute with audit log, notifications, monitoring, re-disruption and
   escalation, LLM layer with template fallback.
4. Map, Bookings, My Trips, History, Profile, Settings, help panel, compensation module.
5. Polish, accessibility, all states, tests, Docker, deployment files, docs.

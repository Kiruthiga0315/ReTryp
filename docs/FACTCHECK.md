# Fact check

Every regulatory, provider and reference fact that is hard-coded in ReTryp,
with the official source it was checked against and the date it was checked.

Rules for this file:

* Append a row whenever a hard-coded value is added or changed.
* If a fact could not be confirmed against a primary source, it is marked
  `TODO: verify` here and in the code.
* Rates and quotas move. Re-check provider rows before relying on them in
  production, and update the date.

## Passenger rights

| Fact | Value used | Source | Checked |
| --- | --- | --- | --- |
| EU261 compensation bands (Article 7(1)) | €250 up to 1,500 km; €400 for 1,500–3,500 km; €600 above 3,500 km | EUR-Lex, Regulation (EC) No 261/2004, Art. 7 — https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex%3A32004R0261 | 2026-09-28 |
| EU261 flight scope (Article 3(1)) | Applies to departures from an EU airport, and to arrivals in the EU on an EU/EEA carrier | EUR-Lex, Regulation (EC) No 261/2004, Art. 3 — same URL | 2026-09-28 |
| EU261 long-haul delay reduction (Article 7(2)) | A re-routed long-haul arrival delayed 3h to under 4h pays half the €600 amount, i.e. €300 | EUR-Lex, Regulation (EC) No 261/2004, Art. 7(2) — same URL | 2026-09-28 |
| EU261 delay trigger (Article 6) | Compensation starts at three hours' arrival delay at the final destination | EUR-Lex, Regulation (EC) No 261/2004, Art. 6 — same URL | 2026-09-28 |
| EU261 extraordinary circumstances (Article 5(3)) | No compensation where the delay was caused by circumstances outside the carrier's control | EUR-Lex, Regulation (EC) No 261/2004, Art. 5(3) — same URL | 2026-09-28 |
| DGCA denied boarding (3.2.2) | 200% of one-way basic fare plus fuel charge capped at INR 10,000 if re-routed within 24h; 400% capped at INR 20,000 beyond that; no compensation if re-routed within 1 hour | DGCA CAR Section 3, Series M, Part IV, Rev. 3 (27 Feb 2019), para 3.2.2 | 2026-09-28 |
| DGCA cancellation (3.3.2) | Fixed band by block time, or the one-way basic fare plus fuel charge, whichever is less: INR 5,000 up to 1h; INR 7,500 for 1–2h; INR 10,000 over 2h, plus a full refund | DGCA CAR Section 3, Series M, Part IV, Rev. 3, para 3.3.2 | 2026-09-28 |
| DGCA delay (3.4) | Care (meals, refreshments) from 2h/3h/4h depending on block time; a refund option after a 6h delay; no cash compensation for delay alone | DGCA CAR Section 3, Series M, Part IV, Rev. 3, para 3.4 | 2026-09-28 |
| DGCA extraordinary circumstances (1.4, 1.5) | No compensation for force majeure, ATC, weather or security causes | DGCA CAR Section 3, Series M, Part IV, Rev. 3, paras 1.4 and 1.5 | 2026-09-28 |

The DGCA CAR text was read from a mirrored copy of the Rev. 3 (27 Feb 2019)
document. The canonical landing page is the DGCA publications index at
https://www.dgca.gov.in/ ; re-download and diff before changing a number.

A correction was made on 2026-09-28: cancellation compensation previously used
the denied-boarding 200%/400% formula. Para 3.3.2 is a fixed block-time band,
which the code (`dgca_cancellation_amount`) and tests now follow.

## Provider limits and policies

| Fact | Value used | Source | Checked |
| --- | --- | --- | --- |
| Nominatim usage policy | Absolute maximum 1 request/second, single thread, identifying `User-Agent` required, results must be cached locally | OSM Foundation Nominatim Usage Policy — https://operations.osmfoundation.org/policies/nominatim | 2026-09-28 |
| Open-Meteo free tier | 600 calls/min, 5,000 calls/hour, 10,000 calls/day, non-commercial | Open-Meteo terms — https://open-meteo.com/en/terms | 2026-09-28 |
| Amadeus Self-Service portal | Was intended for hotel search and rebooking | **Decommissioned 17 July 2026** (new registrations paused March 2026; self-service keys disabled). The portal's free tiers no longer exist, so no Self-Service quota can be relied on. Enterprise APIs are unaffected but need a contract. | Amadeus for Developers portal notice — https://developers.amadeus.com | 2026-09-28 |
| Amadeus Enterprise APIs | Enterprise hotel/air content if a contract exists | Access is per contract, not a free tier. Without a contracted key the app uses DEMO hotels. | Amadeus Enterprise API portal — https://developers.amadeus.com | 2026-09-28 |
| OpenSky API | Anonymous access is rate limited; OAuth2 client credentials raise the limit. `TODO: verify` the current anonymous daily credit before relying on it. | OpenSky Network API docs — https://openskynetwork.github.io/opensky-api/ | 2026-09-28 |

## Data sources and their limits

| Source | Used for | Limitation stated in the UI |
| --- | --- | --- |
| BTS On-Time Performance | Delay-risk priors, US flights only | Never applied to international or Indian routes |
| DGCA on-time performance reports | Delay-risk priors, Indian domestic | Shown as an airline-level aggregate, not per-flight history |
| Eurocontrol / UK CAA punctuality | Delay-risk priors, Europe | Shown as an aggregate, not per-flight history |
| OpenFlights and OurAirports | Airport, airline and route reference | Static reference data, refreshed by rebuild |
| GTFS static and GTFS-Realtime (Transitland, Mobility Database, DELFI/GTFS.de) | Rail, bus and metro timetables and alerts | No official live Indian rail API exists; Indian rail data is CACHED/DEMO and never labelled live |
| OpenStreetMap tiles, Nominatim, OSRM | Maps, geocoding, routing | Attribution shown on the map; Nominatim policy honoured |
| Amadeus Self-Service Hotels | Was planned for hotel search and rebooking | **Decommissioned 17 July 2026.** All hotel results are DEMO. Do not add Self-Service hotel code; a contracted Enterprise key would be a separate integration. |

## Curated tables

| Table | Location | Provenance shown |
| --- | --- | --- |
| Minimum connection times (FRA, BER) | `backend/app/domain/connections.py` | Source name and verified date travel with each assessment |
| Visa and transit rules | `backend/app/domain/visa.py` | Each rule carries a source URL and "last verified" date; the UI always shows "Verify with the embassy or airline before travel" |
| Passenger-rights thresholds | `backend/app/domain/compensation.py` | Regulation reference, URL and verified date travel with each estimate |

## Not verified / known gaps

* Whether this deployment has Amadeus Self-Service hotel access is a
  deployment question, not a code default. Without credentials, all hotel
  results are DEMO, as required.
* Minimum connection times are hard-coded for a small airport set only. Extend
  the table with a sourced figure before using it at another airport.
* Delay-risk priors for non-US, non-EU, non-India routes have no modelled
  source and are reported as unknown rather than guessed.

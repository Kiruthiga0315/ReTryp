# Deploying ReTryp

The frontend is a static build served by a CDN. The backend is a container
that owns the database and the provider integrations. Secrets live only in the
host environment; nothing sensitive is baked into the image or shipped to the
browser.

## Before you deploy

1. Set the account passwords. The bootstrap command creates three accounts
   (traveller, manager, admin); set `BOOTSTRAP_PASSWORD` or let it generate and
   print one, then change it after the first sign-in.
2. Set `COOKIE_SECURE=true` (the API is behind HTTPS in every target below).
3. Set `CORS_ORIGINS` to the exact frontend origin, for example
   `https://retryp.vercel.app`. Multiple origins are comma-separated.
4. Run `pytest -q` in `backend/` and `npm run build` in `frontend/`.

## Docker Compose (single host)

The quickest full-stack run:

```bash
cp .env.example .env          # optional; leave it empty to run on bundled data
docker compose up --build
```

* Frontend: http://localhost:8080
* API: http://localhost:8000, docs at `/docs`

`docker compose` builds the frontend with `VITE_API_BASE` pointing at the
published backend (`http://localhost:8000/api` by default). Override
`VITE_API_BASE` and `CORS_ORIGINS` together when you change the addresses.

The compose file keeps SQLite on a named volume, so data survives restarts.

## Backend on Render

`render.yaml` is a blueprint for the API. Point Render at this repository and
apply it, then set the secrets marked `sync: false` in the dashboard.

* The service builds `backend/Dockerfile` and exposes `/api/health` as its
  health check.
* A 1 GB disk is mounted at `/app/data` for SQLite. For a shared deployment,
  uncomment the `databases` block, provision PostgreSQL, and set
  `DATABASE_URL` to the internal connection string. The Docker entrypoint runs
  `alembic upgrade head` on every boot, so migrations apply automatically.
* Set `CORS_ORIGINS` to your Vercel or custom-domain origin.

The entrypoint applies migrations and creates the sign-in accounts on boot. It
seeds no trips: a trip is one a traveller builds in the Journey Builder.

## Frontend on Vercel

1. Import the repository and set the project root to `frontend/`.
2. Vercel reads `frontend/vercel.json`: `npm run build`, output `dist`, and a
   rewrite so client-side routes resolve to `index.html`.
3. Add an environment variable `VITE_API_BASE` set to the deployed API, for
   example `https://retryp-api.onrender.com/api`.
4. Redeploy. `VITE_*` values are baked in at build time, so changing the API
   URL requires a new build, not just an env change.

Netlify works the same way: build command `npm run build`, publish directory
`dist`, with a `/* -> /index.html 200` redirect.

## Environment variables

| Variable | Where | Notes |
| --- | --- | --- |
| `DATABASE_URL` | backend | `sqlite:////app/data/retryp.db` or a PostgreSQL DSN |
| `CORS_ORIGINS` | backend | Exact frontend origin(s), comma-separated |
| `COOKIE_SECURE` | backend | `true` behind HTTPS |
| `FLIGHT_PROVIDER` | backend | `aerodatabox`, `aviationstack`, `flightaware`; empty auto-detects |
| `AERODATABOX_API_KEY`, `AVIATIONSTACK_API_KEY`, `FLIGHTAWARE_API_KEY` | backend | Flight status |
| `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` | backend | Hotel search and rebooking |
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | backend | Aircraft positions |
| `TRANSITLAND_API_KEY`, `MOBILITY_DATABASE_API_KEY` | backend | GTFS feeds |
| `NOMINATIM_USER_AGENT` | backend | Identifying agent for geocoding |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | backend | Optional; empty disables the LLM |
| `BOOTSTRAP_PASSWORD`, `BOOTSTRAP_*_EMAIL` | backend | Sign-in accounts created on boot |
| `VITE_API_BASE` | frontend build | Full API base URL |

With every optional value empty the app still runs on the bundled reference and
timetable datasets; each value carries its own provenance badge and a source
that cannot answer is shown as unavailable rather than filled in.

## Operational notes

* **Migrations** run on container start (`alembic upgrade head`). To run them
  manually: `docker compose exec backend alembic upgrade head`.
* **Accounts**: `docker compose exec backend python -m app.bootstrap` creates or
  updates the three sign-in accounts. It never seeds trips.
* **Caching and limits**: providers use per-provider TTLs, exponential backoff
  with jitter, and a circuit breaker. When a provider fails or is rate limited,
  ReTryp falls back to the cached reading and labels it CACHED, or reports the
  source as unavailable rather than inventing a value.
* **Server-Sent Events**: the frontend subscribes to `/api/trips/{id}/events`.
  If you put a proxy in front of the API, disable response buffering for that
  path so events flush promptly.
* **Health**: `GET /api/health` returns the service state and the current data
  status. Use it for load-balancer and uptime checks.

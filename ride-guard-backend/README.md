# Ride Fraud & Traffic Intelligence – Backend

FastAPI + PostgreSQL (Neon) backend. Real-time fraud detection (rules + IsolationForest),
live traffic intelligence from drivers' GPS, congestion-aware route suggestions, admin dashboard,
WebSocket alerts. **No paid services and no credit card needed.**

## Free replacements for the paid items in the slides
| Slide tech | Used here (free) | API key? |
|---|---|---|
| AWS | **Render** free web service (AWS free tier needs a card) | no |
| NeonDB | **Neon** free Postgres | connection string |
| Apache Kafka | In-process event queue (`services/stream.py`, Kafka-style producer/consumer) | no |
| Google Maps API | **OSRM** routing + **Nominatim** geocoding (OpenStreetMap) | no |
| Traffic API | Own live congestion from GPS + optional **TomTom** free tier | optional |
| Weather | **Open-Meteo** | no |
| JWT / HTTPS / OAuth | PyJWT, Render HTTPS, **Google Sign-In** (optional) | optional |

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # edit values
uvicorn app.main:app --reload
```
Open http://localhost:8000/docs (Swagger). Click **Authorize**, use your admin email + password.

Load demo data + fraud scenarios + train the ML model:
```bash
python -m scripts.simulate --admin-email admin@example.com --admin-password 'ChangeMe123!'
```

## Getting the keys (all free)

### 1. JWT_SECRET (no signup)
`python -c "import secrets; print(secrets.token_urlsafe(48))"` -> paste in `.env`.

### 2. Neon database -> `DATABASE_URL`
1. Go to https://neon.tech, sign up (GitHub/Google/email, no card).
2. Create a project (any name; pick the region closest to you, e.g. AWS Singapore/Mumbai if offered).
3. On the project dashboard click **Connect**, copy the connection string
   (`postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require`).
4. Put it in `DATABASE_URL`. Tables are created automatically on first start.

### 3. TomTom traffic -> `TOMTOM_API_KEY` (optional)
1. https://developer.tomtom.com -> **Register** (no card).
2. Dashboard -> **Keys**; a default key exists, or **Create a new key** and tick *Traffic API*.
3. Free tier is roughly 2,500 requests/day (check current limits). Used only by `/traffic/flow`
   and `/traffic/routes?external=true`. Without it everything else still works.

### 4. Google Sign-In -> `GOOGLE_CLIENT_ID` (optional)
1. https://console.cloud.google.com -> create a project (no billing required).
2. **APIs & Services -> OAuth consent screen** -> External -> fill app name/email -> save.
3. **Credentials -> Create credentials -> OAuth client ID -> Web application** -> copy the Client ID.
4. Flutter side: `GoogleSignIn(serverClientId: '<that Web client ID>')`, send the resulting
   `idToken` to `POST /auth/google`.

### 5. No key needed
OSRM (routing), Nominatim (address search), Open-Meteo (weather). Fair-use only: OSRM's public server is a
demo (no live traffic, may rate-limit); Nominatim ~1 request/second - set `USER_AGENT` in `.env` to your contact email.

## Deploy free (Render + Neon)
1. Push this folder to a GitHub repo (`.env` is git-ignored).
2. https://render.com -> **New -> Web Service** -> pick the repo.
3. Runtime Python; Build: `pip install -r requirements.txt`;
   Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; Instance type **Free**.
4. Environment variables: everything from `.env.example` (+ `PYTHON_VERSION=3.12.3`).
   Set `CORS_ORIGINS` to your frontend URL once you have it.
5. Free instances sleep after ~15 min idle (first request takes ~1 min). Ping `/health`
   every 10 min with https://uptimerobot.com (free) to keep it awake for demos.
Your API = `https://<name>.onrender.com`, WebSocket = `wss://<name>.onrender.com/ws?token=JWT`.

## API summary (for the frontend)
Auth header: `Authorization: Bearer <token>`

| Method & path | Who | Purpose |
|---|---|---|
| POST `/auth/register` `/auth/login` `/auth/google` | all | returns `{access_token, user}` |
| GET `/auth/me` | any | current user |
| POST `/rides` | passenger | book `{pickup_lat,pickup_lng,drop_lat,drop_lng}` -> ETA/fare estimate |
| GET `/rides/available` | driver | open requests |
| POST `/rides/{id}/accept` `/start` `/complete` | driver | ride lifecycle |
| POST `/rides/{id}/cancel` | passenger/driver | cancel (requested/accepted) |
| POST `/rides/{id}/location` | participants | GPS ping `{lat,lng,speed_kmh,accuracy_m,timestamp}`; send every 3-5 s while ongoing |
| GET `/rides`, `/rides/{id}`, `/rides/{id}/track` | participants | history / live track |
| GET `/traffic/live` | any | congestion cells (colour map) |
| GET `/traffic/routes?olat&olng&dlat&dlng` | any | ranked route alternatives (GeoJSON) |
| GET `/traffic/flow`, `/traffic/weather`, `/geo/search?q=` | any | TomTom speed / weather / address search |
| GET `/admin/dashboard` | admin | all stats + 7-day series |
| GET `/admin/alerts`, POST `/admin/alerts/{id}/resolve` | admin | fraud/traffic alerts |
| GET `/admin/rides?flagged=true`, `/admin/users` | admin | review |
| POST `/admin/users/{id}/suspend?suspended=true` | admin | suspend/reinstate |
| POST `/admin/model/train` | admin | retrain ML model |
| WS `/ws?token=JWT` | any | admin: all alerts; users: own safety notices + traffic notices |

## Fraud signals implemented
`GPS_JUMP`, `SPEED_MISMATCH` (mock-location), `START_LOCATION_MISMATCH`, `LOW_GPS_ACCURACY`,
`ROUTE_DEVIATION`, `DISTANCE_TOO_SHORT`, `LONG_DURATION`, `SHORT_DURATION`, `FARE_INFLATION`,
`REPEATED_CANCELLATIONS`, `RAPID_BOOKINGS`, `TRIVIAL_TRIP`, `REPEAT_PAIR` (collusion), `ML_ANOMALY`.
Each carries a 0-1 score; >= `FRAUD_ALERT_THRESHOLD` (0.6) flags the ride, raises an alert and updates the user's `risk_score`.

## Project layout
```
app/main.py           app + startup        app/routers/   auth, rides, traffic, admin, ws
app/models.py         DB tables            app/services/  fraud, traffic, alerts, stream, pricing
app/ws_manager.py     WebSocket hub        scripts/simulate.py   demo data
```

# RideSafe Frontend

Frontend for the **Cloud-Based Real-Time Ride Fraud and Traffic Intelligence Platform**.
Plain HTML, CSS and JavaScript (as listed on the Technologies slide), with Leaflet for maps and Chart.js for reports.

## Run it

Open a terminal in this folder and run:

    python -m http.server 5500

Then visit http://localhost:5500. (Opening index.html directly also works for demo mode.)

## Demo mode (no backend needed)

`js/config.js` ships with `DEMO_MODE: true`. Log in with any password and one of:

| Email             | Role      |
|-------------------|-----------|
| admin@demo.com    | Admin     |
| driver@demo.com   | Driver    |
| user@demo.com     | Passenger |

## Connect the real backend

1. In `js/config.js` set `DEMO_MODE: false` and `API_BASE` to your friend's server.
2. Make sure the endpoint paths in `config.js` match the backend (edit them there only).
3. The backend must allow CORS from the frontend origin and accept `Authorization: Bearer <token>`.

### Expected responses

| Call | Response shape |
|------|----------------|
| POST /auth/login, /auth/register | `{ token, user: { id, name, email, role } }`, role is `passenger`, `driver` or `admin` |
| GET /rides | `[{ id, pickup, drop, distance_km, fare, status, flagged, created_at, driver, passenger }]` |
| GET /traffic | `[{ zone, lat, lng, congestion (0-100), avg_speed }]` |
| GET /notifications | `[{ id, type, message, created_at }]` |
| GET /admin/stats | `{ total_rides, active_rides, open_alerts, fraud_prevented, avg_congestion, detection_ms }` |
| GET /admin/fraud-alerts | `[{ id, type, detail, risk_score, severity (low/medium/high), user, ride_id, status (open/reviewing/resolved/blocked), created_at }]` |
| GET /admin/users | `[{ id, name, email, role, status, rides, risk }]` |
| GET /admin/reports | `{ fraud_by_type: {type: count}, rides_per_day: [7], fraud_per_day: [7] }` |

## Screens

- **Passenger:** book a ride (with live traffic map and route tip), my rides, live traffic
- **Driver:** go online and share GPS, trips, live traffic
- **Admin:** overview, fraud alerts (review, resolve, confirm), traffic monitor, all rides, users (block/unblock), reports

## Structure

    index.html     <- landing page, sign-in modal, app shell (animated SVG scenes are inline)
    css/styles.css <- theme (colours are CSS variables at the top)
    js/config.js   <- edit this to connect the backend
    js/api.js      <- all API calls and the demo mock data
    js/bg.js       <- animated route-network background
    js/app.js      <- views and logic
    assets/        <- extra SVGs, not used by the pages above

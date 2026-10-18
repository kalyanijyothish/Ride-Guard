import logging
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import GpsPoint, TrafficSegment, utcnow
from ..utils.geo import cell_center, grid_cell, haversine_km
from . import alerts

log = logging.getLogger(__name__)
FRESH_MIN = 15
HEADERS = {"User-Agent": settings.USER_AGENT}


# ---------- internal live congestion (built from our own GPS stream) ----------
def level_for(speed_kmh: float) -> str:
    if speed_kmh < 10:
        return "heavy"
    if speed_kmh < 20:
        return "moderate"
    if speed_kmh < 35:
        return "light"
    return "free"


def ingest_point(db: Session, point: GpsPoint) -> None:
    if point.speed_kmh is None:
        return
    now = utcnow()
    cell = grid_cell(point.lat, point.lng)
    seg = db.get(TrafficSegment, cell)
    if seg is None or (now - seg.updated_at) > timedelta(minutes=FRESH_MIN):
        lat, lng = cell_center(cell)
        if seg is None:
            seg = TrafficSegment(cell=cell, lat=lat, lng=lng)
            db.add(seg)
        seg.avg_speed_kmh, seg.sample_count, seg.vehicles = point.speed_kmh, 1, [point.user_id]
    else:
        seg.avg_speed_kmh = round(0.7 * seg.avg_speed_kmh + 0.3 * point.speed_kmh, 2)
        seg.sample_count += 1
        v = list(seg.vehicles or [])
        if point.user_id not in v:
            v.append(point.user_id)
        seg.vehicles = v[-20:]
    seg.congestion_level = level_for(seg.avg_speed_kmh)
    seg.updated_at = now
    db.commit()

    # Alert only when several *distinct* vehicles confirm it (one parked car isn't a jam)
    if seg.congestion_level == "heavy" and seg.sample_count >= 5 and len(seg.vehicles or []) >= 3:
        alerts.create_alert(
            db, type="traffic", severity="medium",
            title=f"Heavy congestion near {seg.lat:.3f},{seg.lng:.3f}",
            message=f"Heavy congestion detected (avg {seg.avg_speed_kmh:.0f} km/h). Consider alternate routes.",
            details={"cell": cell, "lat": seg.lat, "lng": seg.lng,
                     "avg_speed_kmh": seg.avg_speed_kmh, "vehicles": len(seg.vehicles)},
            to_all=True, dedupe_minutes=15)


def live_segments(db: Session, bbox: tuple[float, float, float, float] | None = None):
    q = db.query(TrafficSegment).filter(TrafficSegment.updated_at >= utcnow() - timedelta(minutes=FRESH_MIN))
    if bbox:
        min_lat, max_lat, min_lng, max_lng = bbox
        q = q.filter(TrafficSegment.lat.between(min_lat, max_lat),
                     TrafficSegment.lng.between(min_lng, max_lng))
    return q.all()


# ---------- OSRM (free, keyless) routing ----------
def osrm_routes(plat, plng, dlat, dlng, geometry: bool = False, alternatives: bool = False) -> list[dict]:
    url = f"{settings.OSRM_URL}/route/v1/driving/{plng},{plat};{dlng},{dlat}"
    params = {"alternatives": "true" if alternatives else "false",
              "overview": "full" if geometry else "false", "geometries": "geojson"}
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=6)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            return []
        return [{"distance_km": rt["distance"] / 1000, "duration_min": rt["duration"] / 60,
                 "geometry": rt.get("geometry")} for rt in data["routes"]]
    except Exception as e:  # network down, rate-limited, etc. -> graceful fallback
        log.warning("OSRM unavailable: %s", e)
        return []


def estimate_route(plat, plng, dlat, dlng) -> tuple[float, float, str]:
    routes = osrm_routes(plat, plng, dlat, dlng)
    if routes:
        return round(routes[0]["distance_km"], 3), round(routes[0]["duration_min"], 2), "osrm"
    d = haversine_km(plat, plng, dlat, dlng) * 1.3
    return round(d, 3), round(d / 25 * 60, 2), "estimate"


_PENALTY = {"heavy": 0.6, "moderate": 0.3, "light": 0.1, "free": 0.0}


def _route_level(p: float) -> str:
    return "free" if p < 0.05 else "light" if p < 0.2 else "moderate" if p < 0.4 else "heavy"


def tomtom_flow(lat: float, lng: float) -> dict | None:
    if not settings.TOMTOM_API_KEY:
        return None
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    try:
        r = httpx.get(url, params={"point": f"{lat},{lng}", "unit": "KMPH",
                                   "key": settings.TOMTOM_API_KEY}, timeout=6)
        r.raise_for_status()
        d = r.json()["flowSegmentData"]
        ratio = d["currentSpeed"] / d["freeFlowSpeed"] if d.get("freeFlowSpeed") else 1.0
        return {"current_speed_kmh": d["currentSpeed"], "free_flow_speed_kmh": d["freeFlowSpeed"],
                "current_travel_time_s": d.get("currentTravelTime"),
                "free_flow_travel_time_s": d.get("freeFlowTravelTime"),
                "congestion_ratio": round(max(0.0, 1 - ratio), 3),
                "road_closure": d.get("roadClosure", False), "confidence": d.get("confidence")}
    except Exception as e:
        log.warning("TomTom flow failed: %s", e)
        return None


def route_options(db: Session, plat, plng, dlat, dlng, external: bool = False) -> list[dict]:
    """Alternative routes ranked by congestion-adjusted ETA (our live data [+ TomTom])."""
    routes = osrm_routes(plat, plng, dlat, dlng, geometry=True, alternatives=True)
    source = "osrm"
    if not routes:
        d = haversine_km(plat, plng, dlat, dlng) * 1.3
        routes = [{"distance_km": d, "duration_min": d / 25 * 60,
                   "geometry": {"type": "LineString", "coordinates": [[plng, plat], [dlng, dlat]]}}]
        source = "estimate"
    live = {s.cell: s for s in live_segments(db)}
    out = []
    for i, rt in enumerate(routes):
        coords = rt["geometry"]["coordinates"]
        step = max(1, len(coords) // 30)
        sample = coords[::step]
        pen = [_PENALTY[live[c].congestion_level] for lng, lat in sample
               if (c := grid_cell(lat, lng)) in live]
        # penalty averaged over *all* sampled points (cells with no data count as free)
        penalty = sum(pen) / len(sample) if sample else 0.0
        if external and settings.TOMTOM_API_KEY:
            mid = coords[len(coords) // 2]
            flow = tomtom_flow(mid[1], mid[0])
            if flow:
                penalty = max(penalty, flow["congestion_ratio"])
        out.append({"id": i, "distance_km": round(rt["distance_km"], 2),
                    "base_duration_min": round(rt["duration_min"], 1),
                    "adjusted_duration_min": round(rt["duration_min"] * (1 + penalty), 1),
                    "congestion_penalty": round(penalty, 3), "congestion_level": _route_level(penalty),
                    "geometry": rt["geometry"], "source": source})
    out.sort(key=lambda r: r["adjusted_duration_min"])
    out[0]["recommended"] = True
    return out


# ---------- keyless extras ----------
def weather(lat: float, lng: float) -> dict | None:
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={
            "latitude": lat, "longitude": lng,
            "current": "temperature_2m,precipitation,weather_code,wind_speed_10m"})
        r.raise_for_status()
        return r.json().get("current")
    except Exception as e:
        log.warning("Open-Meteo failed: %s", e)
        return None


def geocode(q: str, limit: int = 5) -> list[dict]:
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search", headers=HEADERS, timeout=8,
                      params={"q": q, "format": "jsonv2", "limit": limit})
        r.raise_for_status()
        return [{"name": x["display_name"], "lat": float(x["lat"]), "lng": float(x["lon"])} for x in r.json()]
    except Exception as e:
        log.warning("Nominatim failed: %s", e)
        return []

"""Hybrid fraud engine: explainable rules + IsolationForest anomaly model."""
import logging
import os
from datetime import timedelta

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import GpsPoint, Ride, User, utcnow
from ..utils.geo import haversine_km, path_length_km
from . import alerts
from .pricing import compute_fare

log = logging.getLogger(__name__)
MODEL_PATH = os.path.join(settings.MODEL_DIR, "isolation_forest.joblib")
MIN_TRAIN_SAMPLES = 30
_model = None


def sig(code: str, score: float, message: str, **details) -> dict:
    return {"code": code, "score": round(min(1.0, score), 3), "message": message, "details": details}


# ======================= rule checks =======================
def check_booking(db: Session, ride: Ride) -> list[dict]:
    out, now = [], utcnow()
    recent = db.query(func.count(Ride.id)).filter(
        Ride.passenger_id == ride.passenger_id, Ride.id != ride.id,
        Ride.requested_at >= now - timedelta(minutes=10)).scalar() or 0
    if recent >= 4:
        out.append(sig("RAPID_BOOKINGS", 0.5 + 0.1 * recent,
                       f"{recent + 1} ride requests within 10 minutes", count=recent + 1))
    if haversine_km(ride.pickup_lat, ride.pickup_lng, ride.drop_lat, ride.drop_lng) < 0.2:
        out.append(sig("TRIVIAL_TRIP", 0.55, "Pickup and drop-off are almost identical"))
    cancels = _recent_cancels(db, ride.passenger_id)
    if cancels >= 3:
        out.append(sig("REPEATED_CANCELLATIONS", 0.4 + 0.15 * cancels,
                       f"{cancels} cancellations in 24h before a new booking", count=cancels))
    return out


def _recent_cancels(db: Session, user_id: int) -> int:
    return db.query(func.count(Ride.id)).filter(
        Ride.cancelled_by_id == user_id,
        Ride.cancelled_at >= utcnow() - timedelta(hours=24)).scalar() or 0


def check_cancellation(db: Session, ride: Ride, user_id: int) -> list[dict]:
    n = _recent_cancels(db, user_id)
    if n >= 3:
        return [sig("REPEATED_CANCELLATIONS", 0.4 + 0.15 * n,
                    f"User cancelled {n} rides in the last 24h", count=n)]
    return []


def check_gps(ride: Ride, point: GpsPoint, prev: GpsPoint | None, is_first: bool) -> list[dict]:
    out = []
    if is_first:
        d = haversine_km(point.lat, point.lng, ride.pickup_lat, ride.pickup_lng)
        if d > 1.0:
            out.append(sig("START_LOCATION_MISMATCH", 0.6,
                           f"Ride started {d:.1f} km away from the pickup point", distance_km=round(d, 2)))
    if point.accuracy_m and point.accuracy_m > 100:
        out.append(sig("LOW_GPS_ACCURACY", 0.3, f"GPS accuracy is poor ({point.accuracy_m:.0f} m)"))
    if prev is not None:
        dt = (point.ts - prev.ts).total_seconds()
        if dt > 0:
            dist = haversine_km(prev.lat, prev.lng, point.lat, point.lng)
            implied = dist / dt * 3600
            if implied > 200:
                out.append(sig("GPS_JUMP", 0.9, f"Impossible movement: {dist:.1f} km in {dt:.0f}s "
                               f"({implied:.0f} km/h)", implied_kmh=round(implied), distance_km=round(dist, 2)))
            elif implied > 130:
                out.append(sig("GPS_JUMP", 0.6, f"Suspiciously fast movement ({implied:.0f} km/h)",
                               implied_kmh=round(implied)))
            if dt >= 10 and point.speed_kmh and point.speed_kmh > 20 and implied < 2:
                out.append(sig("SPEED_MISMATCH", 0.65, "Device reports movement but location is frozen "
                               "(possible mock-location app)", reported_kmh=point.speed_kmh,
                               implied_kmh=round(implied, 1)))
    return out


def trip_metrics(ride: Ride, points: list[GpsPoint]) -> tuple[float | None, float]:
    pts = sorted(points, key=lambda p: (p.ts, p.id))
    if len(pts) >= 2:
        return (round(path_length_km([(p.lat, p.lng) for p in pts]), 3),
                round((pts[-1].ts - pts[0].ts).total_seconds() / 60, 2))
    start, end = ride.started_at or ride.accepted_at, ride.completed_at or utcnow()
    return None, round(max(0.0, (end - start).total_seconds() / 60), 2)


def check_completed(db: Session, ride: Ride) -> list[dict]:
    out = []
    est_d, est_t = ride.est_distance_km or 0.0, ride.est_duration_min or 0.0
    act_d, act_t = ride.actual_distance_km, ride.actual_duration_min or 0.0

    if act_d is not None and est_d > 1:
        ratio = act_d / est_d
        if ratio > 1.6 and act_d - est_d > 1:
            out.append(sig("ROUTE_DEVIATION", 0.7 + 0.1 * (ratio - 1.6),
                           f"Travelled {act_d:.1f} km vs {est_d:.1f} km expected (x{ratio:.1f})",
                           ratio=round(ratio, 2)))
        elif ratio < 0.4:
            out.append(sig("DISTANCE_TOO_SHORT", 0.6,
                           f"Travelled only {act_d:.1f} km vs {est_d:.1f} km expected", ratio=round(ratio, 2)))
    if est_t > 5:
        if act_t > 3 * est_t + 10:
            out.append(sig("LONG_DURATION", 0.65, f"Ride took {act_t:.0f} min vs {est_t:.0f} expected"))
        elif act_t < 0.3 * est_t:
            out.append(sig("SHORT_DURATION", 0.6, f"Ride took {act_t:.0f} min vs {est_t:.0f} expected"))
    if ride.fare and ride.est_fare and ride.fare > 2 * ride.est_fare and ride.fare - ride.est_fare > 100:
        out.append(sig("FARE_INFLATION", 0.7, f"Final fare {ride.fare} is >2x the estimate {ride.est_fare}"))

    pair = db.query(func.count(Ride.id)).filter(
        Ride.passenger_id == ride.passenger_id, Ride.driver_id == ride.driver_id,
        Ride.status == "completed", Ride.id != ride.id,
        Ride.completed_at >= utcnow() - timedelta(hours=24)).scalar() or 0
    if pair >= 2:
        out.append(sig("REPEAT_PAIR", 0.7, f"Same passenger-driver pair completed {pair + 1} rides in 24h "
                       "(possible collusion / promo abuse)", count=pair + 1))

    s = ml_score(ride)
    if s is not None and s > 0:
        out.append(sig("ML_ANOMALY", s * 0.8, f"Ride is statistically unusual (anomaly {s:.2f})", ml_score=round(s, 3)))
    return out


# ======================= ML model =======================
def _features(ride: Ride) -> list[float] | None:
    dist = ride.actual_distance_km if ride.actual_distance_km is not None else ride.est_distance_km
    dur = ride.actual_duration_min
    if not dist or not dur or dur <= 0:
        return None
    est = ride.est_distance_km or dist
    return [dist, dur, dist / dur * 60, dist / est if est else 1.0, (ride.fare or ride.est_fare) / max(dist, 0.1)]


def train_model(db: Session) -> dict:
    global _model
    rows = db.query(Ride).filter(Ride.status == "completed", Ride.flagged.is_(False)).all()
    X = [f for r in rows if (f := _features(r))]
    if len(X) < MIN_TRAIN_SAMPLES:
        return {"trained": False, "samples": len(X), "reason": f"need >= {MIN_TRAIN_SAMPLES} clean completed rides"}
    m = IsolationForest(n_estimators=150, contamination=0.05, random_state=42).fit(np.array(X))
    os.makedirs(settings.MODEL_DIR, exist_ok=True)
    joblib.dump(m, MODEL_PATH)
    _model = m
    return {"trained": True, "samples": len(X)}


def load_or_train() -> None:
    global _model
    try:
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
            return
        from ..database import SessionLocal
        with SessionLocal() as db:
            train_model(db)
    except Exception as e:  # never block startup on ML
        log.warning("Fraud model unavailable: %s", e)


def ml_score(ride: Ride) -> float | None:
    if _model is None:
        return None
    f = _features(ride)
    if f is None:
        return None
    d = float(_model.decision_function(np.array([f]))[0])  # <0 => anomaly
    return float(min(1.0, max(0.0, -d / 0.15)))


# ======================= aggregate + alert =======================
def apply_signals(db: Session, ride: Ride, signals: list[dict], actor_id: int | None = None, stage: str = ""):
    if not signals:
        return None
    top = max(s["score"] for s in signals)
    fired = [s for s in signals if s["score"] >= settings.FRAUD_ALERT_THRESHOLD]
    ride.fraud_score = max(ride.fraud_score or 0.0, round(top, 3))
    if not fired:
        db.commit()
        return None
    ride.flagged = True
    if actor_id:
        u = db.get(User, actor_id)
        if u:
            u.risk_score = min(1.0, round(u.risk_score * 0.7 + top * 0.5, 3))
    db.commit()
    primary = max(fired, key=lambda s: s["score"])
    notify = [ride.passenger_id] if stage == "gps" else []
    return alerts.create_alert(
        db, type="fraud", severity="high" if top >= 0.8 else "medium",
        title=f"{primary['code']} on ride #{ride.id}", message=primary["message"],
        ride_id=ride.id, user_id=actor_id, notify_user_ids=notify,
        details={"stage": stage, "score": round(top, 3), "signals": fired})


def finalize_ride(db: Session, ride: Ride, points: list[GpsPoint]) -> None:
    """Called when the driver completes a ride: compute metrics, fare, run fraud checks."""
    dist, dur = trip_metrics(ride, points)
    ride.actual_distance_km, ride.actual_duration_min = dist, dur
    ride.fare = compute_fare(dist if dist is not None else ride.est_distance_km, dur)
    ride.status = "completed"
    db.commit()
    apply_signals(db, ride, check_completed(db, ride), actor_id=ride.driver_id, stage="completion")

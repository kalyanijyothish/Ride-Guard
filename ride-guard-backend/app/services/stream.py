"""Kafka-style event pipeline without paying for Kafka.

Endpoints publish GPS events; a background worker consumes them and runs the
fraud + traffic analyzers. STREAM_MODE=inline processes synchronously (handy for tests).
The publish()/handler split mirrors a Kafka producer/consumer, so swapping in a
managed Kafka later only touches this file.
"""
import logging
import queue
import threading

from ..config import settings
from ..database import SessionLocal
from ..models import GpsPoint, Ride
from . import fraud, traffic

log = logging.getLogger(__name__)
_events: "queue.Queue[tuple[str, dict]]" = queue.Queue(maxsize=20000)


def process_gps(point_id: int) -> None:
    with SessionLocal() as db:
        point = db.get(GpsPoint, point_id)
        if not point:
            return
        ride = db.get(Ride, point.ride_id)
        prev = (db.query(GpsPoint)
                .filter(GpsPoint.ride_id == point.ride_id, GpsPoint.id != point.id, GpsPoint.ts <= point.ts)
                .order_by(GpsPoint.ts.desc(), GpsPoint.id.desc()).first())
        total = db.query(GpsPoint).filter(GpsPoint.ride_id == point.ride_id).count()
        fraud.apply_signals(db, ride, fraud.check_gps(ride, point, prev, is_first=(total == 1)),
                            actor_id=point.user_id, stage="gps")
        traffic.ingest_point(db, point)


def publish(topic: str, payload: dict) -> None:
    if settings.STREAM_MODE == "inline":
        _handle(topic, payload)
        return
    try:
        _events.put_nowait((topic, payload))
    except queue.Full:
        log.error("event queue full - dropping %s event", topic)


def _handle(topic: str, payload: dict) -> None:
    try:
        if topic == "gps":
            process_gps(payload["point_id"])
    except Exception:
        log.exception("failed processing %s event", topic)


def _worker() -> None:
    while True:
        topic, payload = _events.get()
        _handle(topic, payload)


def start_worker() -> None:
    threading.Thread(target=_worker, name="stream-worker", daemon=True).start()

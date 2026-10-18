from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import Alert, utcnow
from ..ws_manager import manager


def alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id, "type": a.type, "severity": a.severity, "title": a.title,
        "message": a.message, "ride_id": a.ride_id, "user_id": a.user_id,
        "details": a.details, "status": a.status, "created_at": a.created_at.isoformat(),
    }


def create_alert(db: Session, *, type: str, severity: str, title: str, message: str,
                 ride_id: int | None = None, user_id: int | None = None,
                 details: dict | None = None, notify_user_ids=(), to_all: bool = False,
                 dedupe_minutes: int = 5) -> Alert:
    """Persist an alert and push it live (WebSocket). Duplicate titles for the same ride
    within `dedupe_minutes` are suppressed so GPS streams don't spam admins."""
    q = db.query(Alert).filter(Alert.title == title,
                               Alert.created_at >= utcnow() - timedelta(minutes=dedupe_minutes))
    if ride_id is not None:
        q = q.filter(Alert.ride_id == ride_id)
    existing = q.first()
    if existing:
        return existing

    a = Alert(type=type, severity=severity, title=title, message=message,
              ride_id=ride_id, user_id=user_id, details=details)
    db.add(a)
    db.commit()
    db.refresh(a)

    admin_payload = {"event": "alert", "data": alert_to_dict(a)}
    # Users never see fraud internals - only a short notice.
    user_payload = {"event": "notice", "data": {
        "type": type, "severity": severity, "message": message, "ride_id": ride_id}}
    manager.push(admin_payload, user_payload, user_ids=notify_user_ids, to_all=to_all)
    return a

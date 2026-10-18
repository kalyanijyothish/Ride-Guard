from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models import Alert, Ride, User, utcnow
from ..schemas import AlertOut, RideOut, UserOut
from ..services import fraud, traffic

router = APIRouter(prefix="/admin", tags=["admin"])
Admin = Depends(require_role("admin"))


@router.get("/dashboard")
def dashboard(_: User = Admin, db: Session = Depends(get_db)):
    now = utcnow()
    week = now - timedelta(days=7)

    def n(model, *flt):
        return db.query(func.count(model.id)).filter(*flt).scalar() or 0

    total_rides = n(Ride)
    flagged = n(Ride, Ride.flagged.is_(True))
    status_counts = dict(db.query(Ride.status, func.count(Ride.id)).group_by(Ride.status).all())
    days = [(now - timedelta(days=i)).date().isoformat() for i in range(6, -1, -1)]
    series = {d: {"date": d, "rides": 0, "fraud_alerts": 0, "traffic_alerts": 0} for d in days}
    for (ts,) in db.query(Ride.requested_at).filter(Ride.requested_at >= week).all():
        if ts.date().isoformat() in series:
            series[ts.date().isoformat()]["rides"] += 1
    for ts, typ in db.query(Alert.created_at, Alert.type).filter(Alert.created_at >= week).all():
        k = ts.date().isoformat()
        if k in series and typ in ("fraud", "traffic"):
            series[k][f"{typ}_alerts"] += 1
    risky = db.query(User).filter(User.risk_score > 0).order_by(User.risk_score.desc()).limit(5).all()
    return {
        "users": {"total": n(User), "passengers": n(User, User.role == "passenger"),
                  "drivers": n(User, User.role == "driver"), "suspended": n(User, User.is_active.is_(False))},
        "rides": {"total": total_rides, "by_status": status_counts, "flagged": flagged,
                  "fraud_rate": round(flagged / total_rides, 4) if total_rides else 0.0,
                  "avg_fraud_score": round(db.query(func.avg(Ride.fraud_score)).scalar() or 0, 3),
                  "revenue": round(db.query(func.sum(Ride.fare)).filter(Ride.status == "completed").scalar() or 0, 2)},
        "alerts": {"open_fraud": n(Alert, Alert.type == "fraud", Alert.status == "open"),
                   "open_traffic": n(Alert, Alert.type == "traffic", Alert.status == "open")},
        "traffic": {"congested_cells": sum(1 for s in traffic.live_segments(db) if s.congestion_level == "heavy"),
                    "active_cells": len(traffic.live_segments(db))},
        "last_7_days": list(series.values()),
        "top_risky_users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role,
                             "risk_score": u.risk_score} for u in risky],
    }


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(type: str | None = None, status: str | None = None, severity: str | None = None,
                limit: int = 100, _: User = Admin, db: Session = Depends(get_db)):
    q = db.query(Alert)
    for col, val in ((Alert.type, type), (Alert.status, status), (Alert.severity, severity)):
        if val:
            q = q.filter(col == val)
    return q.order_by(Alert.id.desc()).limit(min(limit, 500)).all()


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, admin: User = Admin, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    a.status, a.resolved_at, a.resolved_by_id = "resolved", utcnow(), admin.id
    db.commit()
    return a


@router.get("/rides", response_model=list[RideOut])
def list_rides(flagged: bool | None = None, status: str | None = None, limit: int = 100,
               _: User = Admin, db: Session = Depends(get_db)):
    q = db.query(Ride)
    if flagged is not None:
        q = q.filter(Ride.flagged.is_(flagged))
    if status:
        q = q.filter(Ride.status == status)
    return q.order_by(Ride.id.desc()).limit(min(limit, 500)).all()


@router.get("/users", response_model=list[UserOut])
def list_users(role: str | None = None, limit: int = 100, _: User = Admin, db: Session = Depends(get_db)):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    return q.order_by(User.risk_score.desc(), User.id).limit(min(limit, 500)).all()


@router.post("/users/{user_id}/suspend", response_model=UserOut)
def set_suspended(user_id: int, suspended: bool = True, admin: User = Admin, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot suspend yourself")
    u.is_active = not suspended
    db.commit()
    return u


@router.post("/model/train")
def train(_: User = Admin, db: Session = Depends(get_db)):
    """(Re)train the IsolationForest on clean completed rides."""
    return fraud.train_model(db)

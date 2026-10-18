from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models import GpsPoint, Ride, User, utcnow
from ..schemas import CancelIn, GpsPointOut, LocationIn, RideCreate, RideOut
from ..services import fraud, stream, traffic
from ..services.pricing import compute_fare

router = APIRouter(prefix="/rides", tags=["rides"])
ACTIVE = ("requested", "accepted", "ongoing")


def _get_ride(db: Session, ride_id: int, user: User, participants_only: bool = True) -> Ride:
    ride = db.get(Ride, ride_id)
    if not ride:
        raise HTTPException(404, "Ride not found")
    if user.role != "admin" and user.id not in (ride.passenger_id, ride.driver_id):
        raise HTTPException(403, "Not your ride")
    return ride


@router.post("", response_model=RideOut, status_code=201)
def book_ride(body: RideCreate, user: User = Depends(require_role("passenger")), db: Session = Depends(get_db)):
    if db.query(Ride).filter(Ride.passenger_id == user.id, Ride.status.in_(ACTIVE)).first():
        raise HTTPException(400, "You already have an active ride")
    dist, dur, source = traffic.estimate_route(body.pickup_lat, body.pickup_lng, body.drop_lat, body.drop_lng)
    ride = Ride(passenger_id=user.id, **body.model_dump(), est_distance_km=dist, est_duration_min=dur,
                est_fare=compute_fare(dist, dur), route_source=source)
    db.add(ride)
    db.commit()
    db.refresh(ride)
    fraud.apply_signals(db, ride, fraud.check_booking(db, ride), actor_id=user.id, stage="booking")
    return ride


@router.get("", response_model=list[RideOut])
def my_rides(status: str | None = None, limit: int = 50, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    q = db.query(Ride)
    if user.role == "passenger":
        q = q.filter(Ride.passenger_id == user.id)
    elif user.role == "driver":
        q = q.filter(Ride.driver_id == user.id)
    if status:
        q = q.filter(Ride.status == status)
    return q.order_by(Ride.id.desc()).limit(min(limit, 200)).all()


@router.get("/available", response_model=list[RideOut])
def available_rides(user: User = Depends(require_role("driver")), db: Session = Depends(get_db)):
    return db.query(Ride).filter(Ride.status == "requested").order_by(Ride.id.desc()).limit(50).all()


@router.get("/{ride_id}", response_model=RideOut)
def get_ride(ride_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ride = db.get(Ride, ride_id)
    if not ride:
        raise HTTPException(404, "Ride not found")
    # drivers may preview a requested ride before accepting
    if user.role == "driver" and ride.status == "requested":
        return ride
    return _get_ride(db, ride_id, user)


@router.post("/{ride_id}/accept", response_model=RideOut)
def accept(ride_id: int, user: User = Depends(require_role("driver")), db: Session = Depends(get_db)):
    if db.query(Ride).filter(Ride.driver_id == user.id, Ride.status.in_(("accepted", "ongoing"))).first():
        raise HTTPException(400, "Finish your current ride first")
    updated = (db.query(Ride).filter(Ride.id == ride_id, Ride.status == "requested")
               .update({"status": "accepted", "driver_id": user.id, "accepted_at": utcnow()}))
    db.commit()
    if not updated:
        raise HTTPException(409, "Ride is no longer available")
    return db.get(Ride, ride_id)


@router.post("/{ride_id}/start", response_model=RideOut)
def start(ride_id: int, user: User = Depends(require_role("driver")), db: Session = Depends(get_db)):
    ride = _get_ride(db, ride_id, user)
    if ride.driver_id != user.id or ride.status != "accepted":
        raise HTTPException(400, "Ride must be accepted by you to start")
    ride.status, ride.started_at = "ongoing", utcnow()
    db.commit()
    return ride


@router.post("/{ride_id}/location", status_code=202)
def push_location(ride_id: int, body: LocationIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """GPS ping. Stored immediately; fraud + traffic analysis runs on the event stream."""
    ride = _get_ride(db, ride_id, user)
    if user.role == "admin" or ride.status != "ongoing":
        raise HTTPException(400, "Location can only be sent for an ongoing ride by its participants")
    now = utcnow()
    ts = min(body.timestamp.replace(tzinfo=None) if body.timestamp else now, now)  # never in the future
    p = GpsPoint(ride_id=ride.id, user_id=user.id, lat=body.lat, lng=body.lng,
                 speed_kmh=body.speed_kmh, accuracy_m=body.accuracy_m, ts=ts)
    db.add(p)
    db.commit()
    stream.publish("gps", {"point_id": p.id})
    return {"accepted": True, "point_id": p.id}


@router.post("/{ride_id}/complete", response_model=RideOut)
def complete(ride_id: int, user: User = Depends(require_role("driver")), db: Session = Depends(get_db)):
    ride = _get_ride(db, ride_id, user)
    if ride.driver_id != user.id or ride.status != "ongoing":
        raise HTTPException(400, "Only the driver of an ongoing ride can complete it")
    ride.completed_at = utcnow()
    points = db.query(GpsPoint).filter(GpsPoint.ride_id == ride.id).all()
    fraud.finalize_ride(db, ride, points)
    db.refresh(ride)
    return ride


@router.post("/{ride_id}/cancel", response_model=RideOut)
def cancel(ride_id: int, body: CancelIn | None = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    ride = _get_ride(db, ride_id, user)
    if user.role == "admin" or ride.status not in ("requested", "accepted"):
        raise HTTPException(400, "Only requested/accepted rides can be cancelled by participants")
    ride.status, ride.cancelled_at, ride.cancelled_by_id = "cancelled", utcnow(), user.id
    ride.cancel_reason = body.reason if body else None
    db.commit()
    fraud.apply_signals(db, ride, fraud.check_cancellation(db, ride, user.id), actor_id=user.id, stage="cancellation")
    return ride


@router.get("/{ride_id}/track", response_model=list[GpsPointOut])
def track(ride_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_ride(db, ride_id, user)
    return db.query(GpsPoint).filter(GpsPoint.ride_id == ride_id).order_by(GpsPoint.ts, GpsPoint.id).all()

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services import traffic as svc

router = APIRouter(prefix="/traffic", tags=["traffic"])
geo = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/live")
def live(min_lat: float | None = None, max_lat: float | None = None,
         min_lng: float | None = None, max_lng: float | None = None,
         _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Live congestion cells built from active drivers' GPS (last 15 min). Optional bounding box."""
    bbox = (min_lat, max_lat, min_lng, max_lng) if None not in (min_lat, max_lat, min_lng, max_lng) else None
    return [{"cell": s.cell, "lat": s.lat, "lng": s.lng, "avg_speed_kmh": s.avg_speed_kmh,
             "congestion_level": s.congestion_level, "vehicles": len(s.vehicles or []),
             "updated_at": s.updated_at.isoformat()} for s in svc.live_segments(db, bbox)]


@router.get("/routes")
def routes(olat: float, olng: float, dlat: float, dlng: float, external: bool = False,
           _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Alternative routes ranked by congestion-adjusted ETA. external=true also consults TomTom (uses quota)."""
    return svc.route_options(db, olat, olng, dlat, dlng, external=external)


@router.get("/flow")
def flow(lat: float, lng: float, _: User = Depends(get_current_user)):
    """Real-time road speed from TomTom (needs TOMTOM_API_KEY)."""
    if not settings.TOMTOM_API_KEY:
        raise HTTPException(501, "TOMTOM_API_KEY not configured")
    data = svc.tomtom_flow(lat, lng)
    if not data:
        raise HTTPException(502, "TomTom request failed")
    return data


@router.get("/weather")
def weather(lat: float, lng: float, _: User = Depends(get_current_user)):
    data = svc.weather(lat, lng)
    if not data:
        raise HTTPException(502, "Weather service unavailable")
    return data


@geo.get("/search")
def search(q: str = Query(min_length=2), _: User = Depends(get_current_user)):
    """Address search via OpenStreetMap Nominatim (free; ~1 req/s - debounce on the client)."""
    return svc.geocode(q)

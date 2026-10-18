from ..config import settings


def compute_fare(distance_km: float, duration_min: float) -> float:
    return round(settings.BASE_FARE + settings.PER_KM * distance_km + settings.PER_MIN * duration_min, 2)

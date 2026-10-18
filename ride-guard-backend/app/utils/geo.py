import math

GRID = 0.005  # ~550 m


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def path_length_km(points) -> float:
    return sum(haversine_km(*points[i], *points[i + 1]) for i in range(len(points) - 1))


def grid_cell(lat: float, lng: float) -> str:
    return f"{round(lat / GRID)}:{round(lng / GRID)}"


def cell_center(cell: str) -> tuple[float, float]:
    a, b = cell.split(":")
    return int(a) * GRID, int(b) * GRID

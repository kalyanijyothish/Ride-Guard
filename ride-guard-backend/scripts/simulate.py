"""Populate a running backend with demo data + fraud scenarios and train the ML model.

    python -m scripts.simulate --base http://localhost:8000 \
        --admin-email admin@example.com --admin-password 'ChangeMe123!'
"""
import argparse
import math
import random
from datetime import datetime, timedelta, timezone

import httpx

CENTER = (16.5062, 80.6480)  # Vijayawada / Amaravati area


def now():
    return datetime.now(timezone.utc)


def km_to_deg(km):
    return km / 111.0


def rnd_point(max_km=8):
    r, a = random.uniform(1, max_km), random.uniform(0, 2 * math.pi)
    return CENTER[0] + km_to_deg(r) * math.cos(a), CENTER[1] + km_to_deg(r) * math.sin(a) / math.cos(math.radians(CENTER[0]))


def haversine(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


class Api:
    def __init__(self, base):
        self.c = httpx.Client(base_url=base, timeout=30)

    def auth(self, email, password, name, role):
        r = self.c.post("/auth/register", json={"email": email, "password": password, "name": name, "role": role})
        if r.status_code == 409:
            r = self.c.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()["user"]["id"]

    def post(self, path, h, **kw):
        r = self.c.post(path, headers=h, **kw)
        r.raise_for_status()
        return r.json()


def drive(api, ride_id, dh, path, speed, t0, jump_at=None, speeds=None):
    """Send GPS pings along `path` with realistic timestamps starting at t0."""
    t = t0
    for i, pt in enumerate(path):
        if i:
            seg = haversine(path[i - 1], pt)
            sp = (speeds[i] if speeds else speed)
            t += timedelta(seconds=max(1, seg / max(sp, 0.1) * 3600))
        api.post(f"/rides/{ride_id}/location", dh, json={
            "lat": pt[0], "lng": pt[1], "speed_kmh": speed if not speeds else speeds[i],
            "accuracy_m": 8, "timestamp": t.isoformat()})
    return t


def line(a, b, n=10):
    return [(a[0] + (b[0] - a[0]) * i / (n - 1), a[1] + (b[1] - a[1]) * i / (n - 1)) for i in range(n)]


def run_ride(api, ph, dh, pickup, drop, path=None, speed=None, cancel=False, journey_min=None):
    ride = api.post("/rides", ph, json={"pickup_lat": pickup[0], "pickup_lng": pickup[1],
                                        "drop_lat": drop[0], "drop_lng": drop[1]})
    if cancel:
        return api.post(f"/rides/{ride['id']}/cancel", ph, json={"reason": "changed my mind"})
    api.post(f"/rides/{ride['id']}/accept", dh)
    api.post(f"/rides/{ride['id']}/start", dh)
    speed = speed or random.uniform(24, 38)
    path = path or line(pickup, drop)
    dist = sum(haversine(path[i], path[i + 1]) for i in range(len(path) - 1))
    t0 = now() - timedelta(hours=dist / speed + 0.02)
    drive(api, ride["id"], dh, path, speed, t0)
    return api.post(f"/rides/{ride['id']}/complete", dh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--admin-email", required=True)
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--rides", type=int, default=60)
    a = ap.parse_args()
    random.seed(7)
    api = Api(a.base)
    admin_h, _ = api.auth(a.admin_email, a.admin_password, "Admin", "passenger")

    drivers = [api.auth(f"driver{i}@demo.com", "Passw0rd!", f"Driver {i}", "driver")[0] for i in range(8)]
    pax = [api.auth(f"rider{i}@demo.com", "Passw0rd!", f"Rider {i}", "passenger")[0] for i in range(20)]
    extra = [api.auth(f"shady{i}@demo.com", "Passw0rd!", f"Shady {i}", "passenger")[0] for i in range(3)]
    print(f"Created {len(drivers)} drivers, {len(pax) + len(extra)} passengers")

    print(f"Simulating {a.rides} normal rides...")
    for i in range(a.rides):
        p, d = rnd_point(), rnd_point()
        if haversine(p, d) < 1.5:
            d = (p[0] + 0.03, p[1] + 0.03)
        run_ride(api, pax[i % 20], drivers[i % 8], p, d)

    print("Scenario 1: GPS teleport (spoofing)")
    p, d = rnd_point(), rnd_point()
    ride = api.post("/rides", extra[0], json={"pickup_lat": p[0], "pickup_lng": p[1], "drop_lat": d[0], "drop_lng": d[1]})
    api.post(f"/rides/{ride['id']}/accept", drivers[0]); api.post(f"/rides/{ride['id']}/start", drivers[0])
    t = now() - timedelta(minutes=10)
    drive(api, ride["id"], drivers[0], [p, (p[0] + 0.001, p[1] + 0.001)], 30, t)
    api.post(f"/rides/{ride['id']}/location", drivers[0], json={
        "lat": p[0] + 0.4, "lng": p[1] + 0.4, "speed_kmh": 30, "timestamp": (t + timedelta(seconds=40)).isoformat()})

    print("Scenario 2: repeated cancellations")
    for _ in range(5):
        p, d = rnd_point(), rnd_point()
        run_ride(api, extra[1], None, p, d, cancel=True)

    print("Scenario 3: route detour (fare padding)")
    p, d = rnd_point(), rnd_point()
    mid = (p[0] + 0.15, p[1] - 0.15)
    run_ride(api, extra[2], drivers[1], p, d, path=line(p, mid, 8) + line(mid, d, 8)[1:])

    print("Scenario 4: congestion (3 drivers crawling in one area)")
    sp = rnd_point()
    spot = (round(sp[0] / 0.005) * 0.005 - 0.0015, round(sp[1] / 0.005) * 0.005)  # stay inside one grid cell
    for k in range(3):
        crawl = [(spot[0] + 0.0004 * j, spot[1]) for j in range(8)]
        ph = pax[k]
        dest = (spot[0] + 0.05, spot[1] + 0.05)
        ride = api.post("/rides", ph, json={"pickup_lat": spot[0], "pickup_lng": spot[1],
                                            "drop_lat": dest[0], "drop_lng": dest[1]})
        api.post(f"/rides/{ride['id']}/accept", drivers[2 + k]); api.post(f"/rides/{ride['id']}/start", drivers[2 + k])
        drive(api, ride["id"], drivers[2 + k], crawl, 5, now() - timedelta(minutes=5))  # rides stay ongoing

    print("Training ML model:", api.post("/admin/model/train", admin_h))
    dash = api.c.get("/admin/dashboard", headers=admin_h).json()
    print("Dashboard:", dash["rides"], dash["alerts"], dash["traffic"])
    for al in api.c.get("/admin/alerts?limit=20", headers=admin_h).json():
        print(f" - [{al['type']}/{al['severity']}] {al['title']}")


if __name__ == "__main__":
    main()

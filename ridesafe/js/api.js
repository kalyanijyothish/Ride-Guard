// ============================================================
//  API layer: talks to the backend, or to built-in mock data in DEMO_MODE
// ============================================================
const API = (() => {
  const C = window.CONFIG;
  const E = C.endpoints;
  const store = {
    get token() { try { return localStorage.getItem("rs_token"); } catch { return null; } },
    set token(v) { try { v ? localStorage.setItem("rs_token", v) : localStorage.removeItem("rs_token"); } catch {} }
  };

  async function http(method, path, body) {
    const res = await fetch(C.API_BASE + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(store.token ? { Authorization: "Bearer " + store.token } : {})
      },
      body: body ? JSON.stringify(body) : undefined
    });
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); msg = j.detail || j.message || msg; } catch {}
      throw new Error(msg);
    }
    return res.status === 204 ? null : res.json();
  }

  // ---------------- demo data ----------------
  const rnd = (a, b) => Math.random() * (b - a) + a;
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const places = ["Benz Circle", "Governorpet", "Autonagar", "Mangalagiri", "Tadepalli", "Gannavaram Airport",
    "Railway Station", "Bus Stand (PNBS)", "Kanuru", "Penamaluru", "Guntur", "Undavalli"];
  const names = ["Ravi Kumar", "Anita Rao", "Suresh Babu", "Lakshmi P", "Karthik R", "Divya S", "Mahesh G", "Priya N"];

  const demo = {
    users: names.map((n, i) => ({
      id: i + 1, name: n, email: n.split(" ")[0].toLowerCase() + "@mail.com",
      role: i % 3 === 0 ? "driver" : "passenger", status: i === 5 ? "blocked" : "active",
      rides: Math.floor(rnd(3, 60)), risk: Math.floor(rnd(2, 95))
    })),
    rides: [],
    alerts: [],
    notifications: [],
    traffic: [
      { zone: "Benz Circle", lat: 16.5017, lng: 80.6550 },
      { zone: "Governorpet", lat: 16.5156, lng: 80.6240 },
      { zone: "Autonagar", lat: 16.4900, lng: 80.6750 },
      { zone: "Mangalagiri", lat: 16.4310, lng: 80.5680 },
      { zone: "Tadepalli", lat: 16.4750, lng: 80.6010 },
      { zone: "Gannavaram", lat: 16.5360, lng: 80.7970 },
      { zone: "Kanuru", lat: 16.4880, lng: 80.7000 },
      { zone: "Railway Stn", lat: 16.5190, lng: 80.6200 }
    ].map(z => ({ ...z, congestion: Math.floor(rnd(10, 95)), avg_speed: Math.floor(rnd(8, 45)) }))
  };

  const fraudTypes = [
    ["Unusual Route", "Route deviates 48% from the optimal path"],
    ["Repeated Cancellation", "7 cancellations in the last 30 minutes"],
    ["GPS Inconsistency", "Location jumped 9 km in 4 seconds"],
    ["Suspicious Booking", "6 bookings from one device, different accounts"],
    ["Abnormal Duration", "Ride took 3.2x the expected duration"],
    ["Fare Anomaly", "Final fare 2.6x the estimate"]
  ];

  function mkAlert(i, minsAgo) {
    const [type, detail] = pick(fraudTypes);
    const score = Math.floor(rnd(55, 99));
    return {
      id: 1000 + i, type, detail, risk_score: score,
      severity: score > 85 ? "high" : score > 70 ? "medium" : "low",
      user: pick(names), ride_id: Math.floor(rnd(4000, 4999)),
      status: "open", created_at: new Date(Date.now() - minsAgo * 60000).toISOString()
    };
  }
  for (let i = 0; i < 9; i++) demo.alerts.push(mkAlert(i, i * 7 + 2));
  for (let i = 0; i < 12; i++) {
    const d = rnd(2, 22);
    demo.rides.push({
      id: 4000 + i, pickup: pick(places), drop: pick(places), distance_km: +d.toFixed(1),
      fare: Math.round(30 + d * 14), status: pick(["completed", "completed", "completed", "cancelled", "ongoing"]),
      flagged: Math.random() < 0.18, created_at: new Date(Date.now() - i * 3600000 * 3).toISOString(),
      driver: pick(names), passenger: pick(names)
    });
  }
  demo.notifications = [
    { id: 1, type: "traffic", message: "Heavy congestion at Benz Circle. Consider the alternate route via Autonagar.", created_at: new Date().toISOString() },
    { id: 2, type: "info", message: "Welcome to RideSafe. All rides are monitored in real time.", created_at: new Date().toISOString() }
  ];

  const delay = (v) => new Promise(r => setTimeout(() => r(structuredClone(v)), 250));
  let alertSeq = 50;

  function jitterTraffic() {
    demo.traffic.forEach(z => {
      z.congestion = Math.max(5, Math.min(99, Math.round(z.congestion + rnd(-9, 9))));
      z.avg_speed = Math.max(5, Math.min(55, Math.round(z.avg_speed + rnd(-4, 4))));
    });
  }

  async function mock(method, key, arg, body) {
    switch (key) {
      case "login": {
        const role = body.email.startsWith("admin") ? "admin" : body.email.startsWith("driver") ? "driver" : "passenger";
        return delay({ token: "demo", user: { id: 99, name: body.email.split("@")[0], email: body.email, role } });
      }
      case "register":
        return delay({ token: "demo", user: { id: 99, name: body.name, email: body.email, role: body.role } });
      case "rides":
        if (method === "POST") {
          const r = { id: 4100 + demo.rides.length, status: "ongoing", flagged: false, created_at: new Date().toISOString(),
            driver: pick(names), passenger: "You", ...body };
          demo.rides.unshift(r); return delay(r);
        }
        return delay(demo.rides);
      case "cancelRide": {
        const r = demo.rides.find(x => x.id == arg); if (r) r.status = "cancelled"; return delay(r);
      }
      case "updateRide": {
        const r = demo.rides.find(x => x.id == arg); if (r) Object.assign(r, body); return delay(r);
      }
      case "location": return delay({ ok: true });
      case "notifications": return delay(demo.notifications);
      case "traffic": jitterTraffic(); return delay(demo.traffic);
      case "adminStats": {
        const open = demo.alerts.filter(a => a.status === "open").length;
        return delay({
          total_rides: 12840 + demo.rides.length, active_rides: 213 + Math.floor(rnd(-12, 12)),
          open_alerts: open, fraud_prevented: 482000,
          avg_congestion: Math.round(demo.traffic.reduce((s, z) => s + z.congestion, 0) / demo.traffic.length),
          detection_ms: Math.floor(rnd(120, 260))
        });
      }
      case "fraudAlerts":
        if (Math.random() < 0.35) demo.alerts.unshift(mkAlert(alertSeq++, 0));
        return delay(demo.alerts);
      case "updateAlert": {
        const a = demo.alerts.find(x => x.id == arg); if (a) Object.assign(a, body); return delay(a);
      }
      case "users": return delay(demo.users);
      case "updateUser": {
        const u = demo.users.find(x => x.id == arg); if (u) Object.assign(u, body); return delay(u);
      }
      case "reports": {
        const counts = {};
        demo.alerts.forEach(a => counts[a.type] = (counts[a.type] || 0) + 1);
        return delay({
          fraud_by_type: counts,
          rides_per_day: [310, 342, 295, 380, 402, 365, 421],
          fraud_per_day: [12, 9, 14, 11, 17, 10, 13]
        });
      }
    }
  }

  async function call(method, key, arg, body) {
    if (C.DEMO_MODE) return mock(method, key, arg, body);
    const ep = typeof E[key] === "function" ? E[key](arg) : E[key];
    return http(method, ep, body);
  }

  return {
    store,
    login: (email, password) => call("POST", "login", null, { email, password }),
    register: (d) => call("POST", "register", null, d),
    getRides: () => call("GET", "rides"),
    bookRide: (d) => call("POST", "rides", null, d),
    cancelRide: (id) => call("POST", "cancelRide", id),
    updateRide: (id, d) => call("PATCH", "updateRide", id, d),
    pingLocation: (lat, lng) => call("POST", "location", null, { lat, lng }),
    getNotifications: () => call("GET", "notifications"),
    getTraffic: () => call("GET", "traffic"),
    getStats: () => call("GET", "adminStats"),
    getAlerts: () => call("GET", "fraudAlerts"),
    setAlert: (id, status) => call("PATCH", "updateAlert", id, { status }),
    getUsers: () => call("GET", "users"),
    setUser: (id, status) => call("PATCH", "updateUser", id, { status }),
    getReports: () => call("GET", "reports")
  };
})();

// ============================================================
//  RideSafe frontend configuration
//  1. Set API_BASE to your friend's Python backend URL.
//  2. Set DEMO_MODE to false once the backend is running.
//  3. If the backend's endpoint paths differ, edit them in `endpoints`.
// ============================================================
window.CONFIG = {
  API_BASE: "http://localhost:8000/api",
  DEMO_MODE: true,          // true = use built-in mock data, no backend needed
  POLL_MS: 6000,            // how often to poll alerts / live data
  MAP_CENTER: [16.5062, 80.6480], // Vijayawada / Amaravati region
  CURRENCY: "₹",

  endpoints: {
    login:          "/auth/login",             // POST {email,password} -> {token,user:{id,name,email,role}}
    register:       "/auth/register",          // POST {name,email,password,role}
    rides:          "/rides",                  // GET (own rides; admin = all) | POST {pickup,drop,distance_km,fare}
    cancelRide:     (id) => `/rides/${id}/cancel`,   // POST
    updateRide:     (id) => `/rides/${id}`,          // PATCH {status}
    location:       "/location",               // POST {lat,lng} (driver GPS ping)
    notifications:  "/notifications",          // GET -> [{id,type,message,created_at}]
    traffic:        "/traffic",                // GET -> [{zone,lat,lng,congestion,avg_speed}]
    adminStats:     "/admin/stats",            // GET
    fraudAlerts:    "/admin/fraud-alerts",     // GET
    updateAlert:    (id) => `/admin/fraud-alerts/${id}`, // PATCH {status}
    users:          "/admin/users",            // GET
    updateUser:     (id) => `/admin/users/${id}`,        // PATCH {status}
    reports:        "/admin/reports"           // GET
  }
};

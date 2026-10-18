
// ============================================================
// RideSafe SPA: landing, auth, role-based views, polling
// ============================================================
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const view = $("#view");
  const C = window.CONFIG;

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const money = (n) => C.CURRENCY + Number(n).toLocaleString("en-IN");
  const ago = (iso) => {
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    return m < 1 ? "just now" : m < 60 ? m + " min ago" :
      m < 1440 ? Math.round(m / 60) + " h ago" :
      Math.round(m / 1440) + " d ago";
  };

  const level = (c) => c >= 70 ? "high" : c >= 40 ? "medium" : "low";
  const barColor = (c) => c >= 70 ? "#ff5a5f" : c >= 40 ? "#f4c430" : "#7fd6a4";

  const state = {
    user: null,
    tab: null,
    timers: [],
    map: null,
    charts: [],
    seenAlerts: new Set(),
    unread: 0,
    userLocationMarker: null,
    userLocationAccuracy: null
  };

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    t.setAttribute("role", "status");
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2800);
  }

  function clearTimers() {
    state.timers.forEach(clearInterval);
    state.timers = [];
  }

  function poll(fn, ms = C.POLL_MS) {
    fn();
    state.timers.push(setInterval(fn, ms));
  }

  function destroyVisuals() {
    state.charts.forEach(c => c.destroy());
    state.charts = [];

    if (state.map) {
      state.map.remove();
      state.map = null;
    }

    state.userLocationMarker = null;
    state.userLocationAccuracy = null;
  }

  // ----------------------------------------------------------
  // MAP + CURRENT LOCATION
  // ----------------------------------------------------------
  function makeMap(id) {
    const map = L.map(id).setView(C.MAP_CENTER, 12);
    state.map = map;

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19
    }).addTo(map);

    const LocateControl = L.Control.extend({
      options: { position: "topleft" },

      onAdd: function () {
        const container = L.DomUtil.create("div", "leaflet-bar");
        const button = L.DomUtil.create("button", "rs-locate-button", container);

        button.type = "button";
        button.title = "Show my current location";
        button.setAttribute("aria-label", "Show my current location");
        button.textContent = "◎";

        button.style.cssText =
          "width:36px;height:36px;border:0;background:#fff;color:#183b2d;" +
          "font-size:24px;line-height:32px;cursor:pointer;font-weight:bold";

        L.DomEvent.disableClickPropagation(container);

        L.DomEvent.on(button, "click", function (event) {
          L.DomEvent.stop(event);

          if (!navigator.geolocation) {
            toast("Your browser does not support location services.");
            return;
          }

          button.disabled = true;
          button.textContent = "…";

          navigator.geolocation.getCurrentPosition(position => {
            const latlng = [
              position.coords.latitude,
              position.coords.longitude
            ];
            const accuracy = position.coords.accuracy || 0;

            if (state.userLocationMarker) {
              map.removeLayer(state.userLocationMarker);
            }

            if (state.userLocationAccuracy) {
              map.removeLayer(state.userLocationAccuracy);
            }

            state.userLocationAccuracy = L.circle(latlng, {
              radius: Math.max(accuracy, 25),
              color: "#2478ff",
              weight: 2,
              fillColor: "#2478ff",
              fillOpacity: 0.12
            }).addTo(map);

            state.userLocationMarker = L.marker(latlng)
              .addTo(map)
              .bindPopup(
                "<b>Your current location</b><br>Latitude: " +
                latlng[0].toFixed(6) +
                "<br>Longitude: " + latlng[1].toFixed(6) +
                "<br>Accuracy: about " + Math.round(accuracy) + " metres"
              );

            map.setView(latlng, 16);
            state.userLocationMarker.openPopup();

            button.disabled = false;
            button.textContent = "◎";
          }, error => {
            button.disabled = false;
            button.textContent = "◎";

            toast(
              error.code === 1
                ? "Location permission denied. Allow location access in browser settings."
                : error.code === 2
                  ? "Location unavailable. Check device location services."
                  : "Location request timed out. Please try again."
            );
          }, {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 10000
          });
        });

        return container;
      }
    });

    map.addControl(new LocateControl());
    return map;
  }

  // ----------------------------------------------------------
  // AUTOMATIC DRIVING DISTANCE
  // ----------------------------------------------------------
  async function geocodePlace(place) {
    const url =
      "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=in&q=" +
      encodeURIComponent(place + ", Vijayawada, Andhra Pradesh, India");

    const response = await fetch(url, {
      headers: { "Accept": "application/json" }
    });

    if (!response.ok) {
      throw new Error("Could not search for location. Please try again.");
    }

    const results = await response.json();

    if (!results.length) {
      throw new Error(
        'Location not found: "' + place +
        '". Try a nearby landmark or full address.'
      );
    }

    return {
      lat: Number(results[0].lat),
      lon: Number(results[0].lon),
      label: results[0].display_name
    };
  }

  async function getDrivingDistanceKm(pickup, drop) {
    const [a, b] = await Promise.all([
      geocodePlace(pickup),
      geocodePlace(drop)
    ]);

    const url =
      "https://router.project-osrm.org/route/v1/driving/" +
      a.lon + "," + a.lat + ";" + b.lon + "," + b.lat +
      "?overview=false&alternatives=false&steps=false";

    const response = await fetch(url);

    if (!response.ok) {
      throw new Error("Could not calculate driving route. Please try again.");
    }

    const data = await response.json();

    if (data.code !== "Ok" || !data.routes || !data.routes.length) {
      throw new Error("No driving route found between these locations.");
    }

    return {
      distanceKm: data.routes[0].distance / 1000,
      durationMin: data.routes[0].duration / 60,
      start: a,
      end: b
    };
  }

  // ----------------------------------------------------------
  // LANDING + AUTHENTICATION
  // ----------------------------------------------------------
  const modal = $("#auth");

  const openAuth = () => {
    modal.classList.remove("hidden");
    setTimeout(() => $("#email").focus(), 30);
  };

  const closeAuth = () => modal.classList.add("hidden");

  document.querySelectorAll("[data-open-auth]").forEach(b =>
    b.addEventListener("click", openAuth)
  );

  $("#authClose").addEventListener("click", closeAuth);

  modal.addEventListener("click", e => {
    if (e.target === modal) closeAuth();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeAuth();
  });

  let mode = "login";

  $("#authMode").addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;

    mode = b.dataset.mode;

    document.querySelectorAll("#authMode button").forEach(x =>
      x.classList.toggle("on", x === b)
    );

    $("#nameRow").classList.toggle("hidden", mode !== "register");
    $("#roleRow").classList.toggle("hidden", mode !== "register");

    $("#authTitle").textContent =
      $("#authSubmit").textContent =
        mode === "login" ? "Sign in" : "Create account";

    $("#authError").textContent = "";
  });

  if (!C.DEMO_MODE) {
    $("#demoNote").classList.add("hidden");
    $("#demoPick").classList.add("hidden");
  }

  async function finishLogin(res) {
    API.store.token = res.token;

    try {
      localStorage.setItem("rs_user", JSON.stringify(res.user));
    } catch {}

    start(res.user);
  }

  document.querySelectorAll("[data-demo]").forEach(b =>
    b.addEventListener("click", async () => {
      b.disabled = true;

      try {
        await finishLogin(await API.login(b.dataset.demo, "demo"));
      } catch (ex) {
        toast(ex.message || "Could not start the demo");
      }

      b.disabled = false;
    })
  );

  $("#authForm").addEventListener("submit", async e => {
    e.preventDefault();

    const email = $("#email").value.trim();
    const password = $("#password").value;
    const err = $("#authError");

    err.textContent = "";

    if (!/^\S+@\S+\.\S+$/.test(email)) {
      err.textContent = "Enter a valid email address.";
      return;
    }

    if (password.length < 4) {
      err.textContent = "Password is too short.";
      return;
    }

    if (mode === "register" && !$("#name").value.trim()) {
      err.textContent = "Enter your name.";
      return;
    }

    const btn = $("#authSubmit");
    btn.disabled = true;

    try {
      await finishLogin(
        mode === "login"
          ? await API.login(email, password)
          : await API.register({
              name: $("#name").value.trim(),
              email,
              password,
              role: $("#role").value
            })
      );
    } catch (ex) {
      err.textContent = ex.message || "Could not sign in.";
    }

    btn.disabled = false;
  });

  $("#logoutBtn").addEventListener("click", () => {
    clearTimers();
    destroyVisuals();
    API.store.token = null;

    try {
      localStorage.removeItem("rs_user");
    } catch {}

    state.user = null;
    $("#app").classList.add("hidden");
    $("#landing").classList.remove("hidden");
    scrollTo(0, 0);
  });

  // ----------------------------------------------------------
  // ROLE-BASED NAVIGATION
  // ----------------------------------------------------------
  const TABS = {
    passenger: [
      ["book", "Book a Ride"],
      ["rides", "My Rides"],
      ["traffic", "Live Traffic"]
    ],
    driver: [
      ["drive", "Drive"],
      ["rides", "My Trips"],
      ["traffic", "Live Traffic"]
    ],
    admin: [
      ["overview", "Overview"],
      ["fraud", "Fraud Alerts"],
      ["trafficAdmin", "Traffic Monitor"],
      ["allrides", "Rides"],
      ["users", "Users"],
      ["reports", "Reports"]
    ]
  };

  const VIEWS = {
    book, rides, traffic, drive,
    overview, fraud, trafficAdmin, allrides, users, reports
  };

  function start(user) {
    state.user = user;

    closeAuth();
    $("#landing").classList.add("hidden");
    $("#app").classList.remove("hidden");
    scrollTo(0, 0);

    $("#roleBadge").textContent = user.role;
    $("#userName").textContent = user.name;

    const tabs = TABS[user.role] || TABS.passenger;

    $("#tabs").innerHTML = tabs.map(([k, l]) =>
      `<button class="tab" role="tab" data-tab="${k}">${l}</button>`
    ).join("");

    notifs = [];
    state.unread = 0;
    renderBell();
    go(tabs[0][0]);
  }

  $("#tabs").addEventListener("click", e => {
    const b = e.target.closest(".tab");
    if (b) go(b.dataset.tab);
  });

  function go(tab) {
    state.tab = tab;

    document.querySelectorAll(".tab").forEach(t => {
      const on = t.dataset.tab === tab;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", on);
    });

    clearTimers();
    poll(loadNotifications, C.POLL_MS * 2);
    destroyVisuals();
    view.innerHTML = "";
    VIEWS[tab]();
  }

// ----------------------------------------------------------
// NOTIFICATIONS
// ----------------------------------------------------------
let notifs = [];

async function loadNotifications() {
  try {
    const n = await API.getNotifications();
    const known = new Set(notifs.map(x => x.id));

    if (notifs.length) {
      state.unread += n.filter(x => !known.has(x.id)).length;
    }

    notifs = n;
    renderBell();
  } catch {}
}

function renderBell() {
  $("#bellDot").classList.toggle("hidden", state.unread === 0);

  $("#notifPanel").innerHTML = notifs.length
    ? notifs.map(n =>
        `<div class="notif"><b>${esc(n.type)}</b> · ${esc(n.message)}
        <div class="muted small">${ago(n.created_at)}</div></div>`
      ).join("")
    : `<div class="empty">No notifications</div>`;
}

$("#bellBtn").addEventListener("click", () => {
  $("#notifPanel").classList.toggle("hidden");
  state.unread = 0;
  renderBell();
});

document.addEventListener("click", e => {
  if (!e.target.closest("#bellBtn, #notifPanel")) {
    $("#notifPanel").classList.add("hidden");
  }
});

// ----------------------------------------------------------
// SHARED COMPONENTS
// ----------------------------------------------------------
function art() {
  if (state.user && state.user.role === "admin") {
    return `<svg viewBox="0 0 210 110" width="100%" height="100%">
      <g fill="none" stroke="#7fd6a4" stroke-opacity=".35">
        <circle cx="105" cy="55" r="18"/>
        <circle cx="105" cy="55" r="36"/>
        <circle cx="105" cy="55" r="54"/>
        <path d="M105 1V109M51 55H159"/>
      </g>
      <g class="sweep">
        <path d="M105 55 L105 1 A54 54 0 0 1 143 17 Z"
          fill="#7fd6a4" fill-opacity=".28"/>
      </g>
      <circle class="blip" cx="140" cy="36" r="4" fill="#ff5a5f"/>
      <circle class="blip" style="animation-delay:1.3s"
        cx="72" cy="72" r="4" fill="#f4c430"/>
      <circle class="blip" style="animation-delay:2.6s"
        cx="124" cy="82" r="3.5" fill="#7fd6a4"/>
    </svg>`;
  }

  return `<svg viewBox="0 0 210 110" width="100%" height="100%">
    <path d="M0 98H210" stroke="#1d3a31" stroke-width="10"/>
    <path d="M0 98H210" stroke="#7fd6a4" stroke-opacity=".5"
      stroke-width="2" stroke-dasharray="14 14">
      <animate attributeName="stroke-dashoffset" from="0" to="-28"
        dur=".8s" repeatCount="indefinite"/>
    </path>
    <g transform="translate(34 6) scale(.9)">
      <g class="bob">
        <path d="M28 38 Q30 16 70 16 L108 18 Q120 20 124 34
          L124 40 L28 40 Z" fill="#0f7a54"/>
        <rect x="26" y="40" width="98" height="28" rx="7" fill="#f4c430"/>
        <rect x="36" y="25" width="42" height="12" rx="3"
          fill="#bfe9ff" fill-opacity=".45"/>
        <path d="M112 22 L124 36 L112 38 Z"
          fill="#bfe9ff" fill-opacity=".45"/>
        <circle cx="125" cy="52" r="3.2" fill="#fff6c9"/>
        <path d="M126 56 L137 80" stroke="#cfd8d2"
          stroke-width="3" stroke-linecap="round"/>
      </g>
      <g class="wheel" style="transform-origin:52px 80px">
        <circle cx="52" cy="80" r="13" fill="#10201b"
          stroke="#cfd8d2" stroke-width="2"/>
        <path d="M52 69v22M41 80h22" stroke="#cfd8d2" stroke-width="2"/>
      </g>
      <g class="wheel" style="transform-origin:137px 80px">
        <circle cx="137" cy="80" r="11" fill="#10201b"
          stroke="#cfd8d2" stroke-width="2"/>
        <path d="M137 71v18M128 80h18" stroke="#cfd8d2" stroke-width="2"/>
      </g>
    </g>
  </svg>`;
}

function head(title, sub, right = "") {
  return `<section class="banner">
    <div>
      <h1>${title}</h1>
      <div class="sub">${sub}</div>
      ${right ? `<div class="extra">${right}</div>` : ""}
    </div>
    <div class="art" aria-hidden="true">${art()}</div>
  </section>`;
}

function ridesTable(list, opts = {}) {
  if (!list.length) return `<div class="empty">No rides yet.</div>`;

  return `<div class="table-wrap"><table>
    <thead><tr>
      <th>ID</th><th>Route</th><th>Distance</th><th>Fare</th><th>Status</th>
      ${opts.people ? "<th>Passenger</th><th>Driver</th>" : ""}
      <th>When</th>${opts.actions ? "<th></th>" : ""}
    </tr></thead>
    <tbody>${list.map(r => `<tr>
      <td>#${r.id}${r.flagged
        ? ` <span class="chip high" title="Flagged by fraud model">flagged</span>`
        : ""}</td>
      <td>${esc(r.pickup)} → ${esc(r.drop)}</td>
      <td>${r.distance_km} km</td>
      <td>${money(r.fare)}</td>
      <td><span class="chip ${esc(r.status)}">${esc(r.status)}</span></td>
      ${opts.people
        ? `<td>${esc(r.passenger)}</td><td>${esc(r.driver)}</td>`
        : ""}
      <td class="muted small">${ago(r.created_at)}</td>
      ${opts.actions ? `<td>${opts.actions(r)}</td>` : ""}
    </tr>`).join("")}</tbody>
  </table></div>`;
}

function trafficBars(zones) {
  return [...zones]
    .sort((a, b) => b.congestion - a.congestion)
    .map(z => `<div class="bar-row">
      <span>${esc(z.zone)}</span>
      <div class="bar" role="img"
        aria-label="${esc(z.zone)} ${z.congestion}% congested">
        <i style="width:${z.congestion}%;background:${barColor(z.congestion)}"></i>
      </div>
      <span class="muted small">${z.congestion}%</span>
    </div>`).join("");
}

function drawTrafficMap(zones, layerRef) {
  if (!state.map) return;

  if (layerRef.g) layerRef.g.remove();
  layerRef.g = L.layerGroup().addTo(state.map);

  zones.forEach(z =>
    L.circleMarker([z.lat, z.lng], {
      radius: 8 + z.congestion / 8,
      color: barColor(z.congestion),
      fillColor: barColor(z.congestion),
      fillOpacity: .45,
      weight: 2
    })
      .bindPopup(
        `<b>${esc(z.zone)}</b><br>Congestion ${z.congestion}%<br>
        Avg speed ${z.avg_speed} km/h`
      )
      .addTo(layerRef.g)
  );
}

function suggestRoute(zones) {
  if (!zones.length) return "Traffic information is unavailable.";

  const worst = [...zones].sort((a, b) => b.congestion - a.congestion)[0];
  const best = [...zones].sort((a, b) => a.congestion - b.congestion)[0];

  if (worst.congestion < 60) {
    return "Roads look clear. Expect normal travel time.";
  }

  return `Heavy congestion near <b>${esc(worst.zone)}</b>
    (${worst.congestion}%). Consider routing via
    <b>${esc(best.zone)}</b> (${best.congestion}%) to save time.`;
}

// ----------------------------------------------------------
// PASSENGER: BOOK A RIDE
// ----------------------------------------------------------
function book() {
  const layer = {};

  view.innerHTML = head(
    "Book a ride",
    "Enter pickup and drop locations to calculate road distance automatically."
  ) + `
    <div class="grid g-main">
      <div class="card">
        <div class="card-head"><h2>Ride details</h2></div>
        <form id="bookForm" novalidate>
          <label for="pickup">Pickup</label>
          <input id="pickup" list="places"
            placeholder="e.g. Benz Circle" autocomplete="street-address" required>

          <label for="drop">Drop</label>
          <input id="drop" list="places"
            placeholder="e.g. Gannavaram Airport" autocomplete="street-address" required>

          <datalist id="places">
            <option>Benz Circle</option>
            <option>Governorpet</option>
            <option>Autonagar</option>
            <option>Mangalagiri</option>
            <option>Tadepalli</option>
            <option>Gannavaram Airport</option>
            <option>Railway Station</option>
            <option>VIT-AP University</option>
          </datalist>

          <label for="dist">Driving distance (km)</label>
          <input id="dist" type="number" min="0.1" max="500" step="0.1"
            placeholder="Calculated automatically" readonly aria-readonly="true">

          <div class="small muted" id="distanceStatus" aria-live="polite"
            style="margin-top:6px">
            Enter pickup and drop to calculate the route.
          </div>

          <div class="live-banner" style="margin-top:16px">
            <span>Estimated fare</span><span class="spacer"></span>
            <b id="fare" style="font-family:var(--head);font-size:1.5rem">—</b>
          </div>

          <div class="small muted" id="routeTip" style="margin-bottom:14px"></div>
          <p class="error" id="bookErr" role="alert"></p>
          <button class="btn" id="bookSubmit" style="width:100%">
            Confirm booking
          </button>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h2>Traffic nearby</h2><span class="chip">live</span></div>
        <div id="map" class="map"></div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-head"><h2>Current ride</h2></div>
      <div id="current"></div>
    </div>`;

  makeMap("map");

  let routeRequest = 0;
  let calculatedRoute = null;

  const pickupInput = $("#pickup");
  const dropInput = $("#drop");
  const distanceInput = $("#dist");
  const fareOutput = $("#fare");
  const distanceStatus = $("#distanceStatus");
  const submitButton = $("#bookSubmit");

  const updateRoute = async () => {
    const requestId = ++routeRequest;
    const p = pickupInput.value.trim();
    const d = dropInput.value.trim();

    calculatedRoute = null;
    distanceInput.value = "";
    fareOutput.textContent = "—";
    submitButton.disabled = true;
    $("#bookErr").textContent = "";

    if (!p || !d) {
      distanceStatus.textContent = "Enter pickup and drop to calculate the route.";
      submitButton.disabled = false;
      return;
    }

    if (p.toLowerCase() === d.toLowerCase()) {
      distanceStatus.textContent = "Pickup and drop must be different.";
      return;
    }

    distanceStatus.textContent =
      "Finding locations and calculating driving distance…";

    try {
      const route = await getDrivingDistanceKm(p, d);

      if (requestId !== routeRequest) return;

      calculatedRoute = route;

      const km = Math.round(route.distanceKm * 10) / 10;
      distanceInput.value = km.toFixed(1);
      fareOutput.textContent = money(Math.round(30 + route.distanceKm * 14));

      distanceStatus.textContent =
        "Road distance calculated. Estimated driving time: " +
        Math.round(route.durationMin) + " minutes.";

      submitButton.disabled = false;

      if (state.map) {
        const points = [
          [route.start.lat, route.start.lon],
          [route.end.lat, route.end.lon]
        ];

        state.map.fitBounds(L.latLngBounds(points).pad(.2));

        if (layer.route) layer.route.remove();

        layer.route = L.layerGroup().addTo(state.map);

        L.polyline(points, {
          color: "#2478ff",
          weight: 4,
          dashArray: "8 8"
        }).addTo(layer.route);

        L.marker(points[0]).addTo(layer.route)
          .bindPopup("Pickup: " + esc(p));

        L.marker(points[1]).addTo(layer.route)
          .bindPopup("Drop: " + esc(d));
      }
    } catch (ex) {
      if (requestId !== routeRequest) return;

      distanceStatus.textContent =
        ex.message || "Unable to calculate the route.";

      submitButton.disabled = true;
    }
  };

  [pickupInput, dropInput].forEach(input => {
    input.addEventListener("change", updateRoute);
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") {
        e.preventDefault();
        updateRoute();
      }
    });
  });

  const renderCurrent = async () => {
    try {
      const list = await API.getRides();
      const cur = list.find(r => r.status === "ongoing");

      $("#current").innerHTML = cur ? `
        <div class="live-banner">
          <span class="pulse"></span>
          <div>
            <b>Ride #${cur.id} in progress</b>
            <div class="small muted">
              ${esc(cur.pickup)} → ${esc(cur.drop)} · ${money(cur.fare)}
              · monitored in real time
            </div>
          </div>
          <span class="spacer"></span>
          <button class="btn ghost sm" id="cancelBtn">Cancel ride</button>
        </div>`
        : `<div class="empty">No active ride. Fill in the form to book one.</div>`;

      const cb = $("#cancelBtn");

      if (cb) {
        cb.onclick = async () => {
          await API.cancelRide(cur.id);
          toast("Ride cancelled");
          renderCurrent();
        };
      }
    } catch {}
  };

  renderCurrent();

  poll(async () => {
    try {
      const zones = await API.getTraffic();
      drawTrafficMap(zones, layer);
      $("#routeTip").innerHTML = suggestRoute(zones);
    } catch {}
  });

  $("#bookForm").addEventListener("submit", async e => {
    e.preventDefault();

    const p = pickupInput.value.trim();
    const d = dropInput.value.trim();
    const err = $("#bookErr");

    err.textContent = "";

    if (!p || !d) {
      err.textContent = "Enter pickup and drop locations.";
      return;
    }

    if (p.toLowerCase() === d.toLowerCase()) {
      err.textContent = "Pickup and drop must be different.";
      return;
    }

    if (!calculatedRoute || !distanceInput.value) {
      err.textContent =
        "Wait for the driving distance to be calculated successfully.";
      return;
    }

    submitButton.disabled = true;

    try {
      await API.bookRide({
        pickup: p,
        drop: d,
        distance_km: Math.round(calculatedRoute.distanceKm * 10) / 10,
        fare: Math.round(30 + calculatedRoute.distanceKm * 14)
      });

      toast("Ride booked");
      renderCurrent();
    } catch (ex) {
      err.textContent = ex.message || "Could not book the ride.";
    } finally {
      submitButton.disabled = false;
    }
  });
}

// ----------------------------------------------------------
// RIDE HISTORY
// ----------------------------------------------------------
function rides() {
  const isDriver = state.user.role === "driver";

  view.innerHTML = head(
    isDriver ? "My trips" : "My rides",
    "Your ride history"
  ) + `<div class="card" id="list"></div>`;

  const load = async () => {
    const list = await API.getRides();

    $("#list").innerHTML = ridesTable(list, {
      actions: isDriver ? undefined : r =>
        r.status === "ongoing"
          ? `<button class="btn ghost sm" data-c="${r.id}">Cancel</button>`
          : ""
    });

    document.querySelectorAll("[data-c]").forEach(b => {
      b.onclick = async () => {
        await API.cancelRide(b.dataset.c);
        toast("Ride cancelled");
        load();
      };
    });
  };

  poll(load, C.POLL_MS * 2);
}

// ----------------------------------------------------------
// LIVE TRAFFIC
// ----------------------------------------------------------
function traffic() {
  const layer = {};

  view.innerHTML = head(
    "Live traffic",
    "Congestion across the city, refreshed continuously."
  ) + `
    <div class="grid g-main">
      <div class="card"><div id="map" class="map tall"></div></div>
      <div class="card">
        <div class="card-head"><h2>Congestion by zone</h2></div>
        <div id="bars"></div>
        <div class="live-banner" style="margin-top:12px">
          <div class="small" id="tip"></div>
        </div>
      </div>
    </div>`;

  makeMap("map");

  poll(async () => {
    try {
      const z = await API.getTraffic();
      drawTrafficMap(z, layer);
      $("#bars").innerHTML = trafficBars(z);
      $("#tip").innerHTML = suggestRoute(z);
    } catch {}
  });
}

// ----------------------------------------------------------
// DRIVER CONSOLE
// ----------------------------------------------------------
function drive() {
  let online = false;
  let last = null;

  view.innerHTML = head(
    "Driver console",
    "Go online to share your live GPS location.",
    `<button class="btn" id="onlineBtn">Go online</button>`
  ) + `
    <div class="grid g-main">
      <div class="card"><div id="map" class="map tall"></div></div>
      <div class="grid">
        <div class="card" id="status"></div>
        <div class="card">
          <div class="card-head"><h2>Traffic ahead</h2></div>
          <div id="bars"></div>
        </div>
      </div>
    </div>`;

  const m = makeMap("map");
  let marker = null;
  const layer = {};

  const paint = () => {
    $("#status").innerHTML = online
      ? `<div class="live-banner">
          <span class="pulse"></span>
          <div>
            <b>You're online</b>
            <div class="small muted">
              GPS ping every few seconds
              ${last ? ` · ${last[0].toFixed(4)}, ${last[1].toFixed(4)}` : ""}
            </div>
          </div>
        </div>
        <p class="small muted">
          Abnormal routes or location jumps are flagged to the fraud team.
        </p>`
      : `<div class="empty">You're offline. Passengers can't see you.</div>`;

    $("#onlineBtn").textContent = online ? "Go offline" : "Go online";
    $("#onlineBtn").className = online ? "btn ghost" : "btn";
  };

  paint();

  const ping = () => {
    if (!online) return;

    if (!navigator.geolocation) {
      toast("Your browser does not support location services.");
      return;
    }

    navigator.geolocation.getCurrentPosition(p => {
      last = [p.coords.latitude, p.coords.longitude];

      API.pingLocation(last[0], last[1]).catch(() => {});

      if (!marker) {
        marker = L.marker(last).addTo(m);
      } else {
        marker.setLatLng(last);
      }

      m.setView(last, 14);
      paint();
    }, () => {
      toast("Unable to get your location. Check browser permissions.");
    }, {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 5000
    });
  };

  $("#onlineBtn").onclick = () => {
    online = !online;

    if (!online && marker) {
      marker.remove();
      marker = null;
    }

    paint();

    if (online) ping();
  };

  state.timers.push(setInterval(ping, 5000));

  poll(async () => {
    try {
      const z = await API.getTraffic();
      $("#bars").innerHTML = trafficBars(z);
      drawTrafficMap(z, layer);
    } catch {}
  });
}

// ----------------------------------------------------------
// ADMIN OVERVIEW
// ----------------------------------------------------------
function overview() {
  view.innerHTML = head(
    "Overview",
    "Fraud, traffic and ride activity at a glance."
  ) + `
    <div class="grid g4" id="stats"></div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card">
        <div class="card-head">
          <h2>Latest fraud alerts</h2>
          <button class="btn ghost sm" id="toFraud">View all</button>
        </div>
        <div id="recent"></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Traffic congestion</h2></div>
        <div id="bars"></div>
      </div>
    </div>`;

  $("#toFraud").onclick = () => go("fraud");

  poll(async () => {
    try {
      const [s, a, t] = await Promise.all([
        API.getStats(),
        API.getAlerts(),
        API.getTraffic()
      ]);

      const cards = [
        ["Total rides", s.total_rides.toLocaleString("en-IN"), "all time"],
        ["Active rides", s.active_rides, "right now"],
        ["Open alerts", s.open_alerts, "need review"],
        ["Fraud prevented", money(s.fraud_prevented), "estimated"]
      ];

      $("#stats").innerHTML = cards.map(([l, v, sub]) =>
        `<div class="card stat">
          <div class="label">${l}</div>
          <div class="value">${v}</div>
          <div class="sub">${sub}</div>
        </div>`
      ).join("");

      $("#recent").innerHTML =
        a.filter(x => x.status === "open")
          .slice(0, 4)
          .map(x => alertItem(x))
          .join("") ||
        `<div class="empty">All clear. No open alerts.</div>`;

      $("#bars").innerHTML = trafficBars(t);
      bindAlertActions(() => go("overview"));
    } catch {}
  });
}

function alertItem(a, fresh) {
  const actions = a.status === "open"
    ? `<button class="btn ghost sm" data-a="${a.id}" data-s="reviewing">Review</button>
       <button class="btn sm" data-a="${a.id}" data-s="resolved">Resolve</button>
       <button class="btn danger sm" data-a="${a.id}" data-s="blocked">Confirm fraud</button>`
    : `<span class="chip ${esc(a.status)}">${esc(a.status)}</span>`;

  return `<div class="alert-item ${esc(a.severity)} ${fresh ? "fresh" : ""}">
    <div class="score" title="Risk score">${a.risk_score}</div>
    <div>
      <b>${esc(a.type)}</b>
      <span class="chip ${esc(a.severity)}">${esc(a.severity)}</span>
      <div class="small">${esc(a.detail)}</div>
      <div class="small muted">
        ${esc(a.user)} · ride #${a.ride_id} · ${ago(a.created_at)}
      </div>
    </div>
    <div class="alert-actions">${actions}</div>
  </div>`;
}

function bindAlertActions(after) {
  document.querySelectorAll("[data-a]").forEach(b => {
    b.onclick = async () => {
      await API.setAlert(b.dataset.a, b.dataset.s);
      toast("Alert marked " + b.dataset.s);
      after();
    };
  });
}

// ----------------------------------------------------------
// FRAUD ALERTS
// ----------------------------------------------------------
function fraud() {
  let filter = "open";

  view.innerHTML = head(
    "Fraud alerts",
    "Detected in real time by the AI/ML model."
  ) + `
    <div class="filters" id="filters">
      ${["open", "reviewing", "resolved", "blocked", "all"].map(f =>
        `<button class="btn ghost sm" data-f="${f}">
          ${f === "blocked" ? "confirmed fraud" : f}
        </button>`
      ).join("")}
    </div>
    <div class="card" id="alerts"></div>`;

  const load = async () => {
    try {
      const list = await API.getAlerts();

      document.querySelectorAll("#filters .btn").forEach(b =>
        b.classList.toggle("on", b.dataset.f === filter)
      );

      const shown = list.filter(a => filter === "all" || a.status === filter);
      const newIds = shown
        .filter(a => !state.seenAlerts.has(a.id))
        .map(a => a.id);
      const first = state.seenAlerts.size === 0;

      list.forEach(a => state.seenAlerts.add(a.id));

      $("#alerts").innerHTML =
        shown.map(a => alertItem(a, !first && newIds.includes(a.id))).join("") ||
        `<div class="empty">No alerts in this view.</div>`;

      if (!first && newIds.length && filter === "open") {
        toast(`${newIds.length} new fraud alert${newIds.length > 1 ? "s" : ""}`);
      }

      bindAlertActions(load);
    } catch {}
  };

  $("#filters").onclick = e => {
    const b = e.target.closest("[data-f]");
    if (b) {
      filter = b.dataset.f;
      load();
    }
  };

  poll(load, 4000);
}

function trafficAdmin() {
  traffic();
}

// ----------------------------------------------------------
// ADMIN: ALL RIDES
// ----------------------------------------------------------
function allrides() {
  view.innerHTML = head(
    "All rides",
    "Every ride on the platform, with fraud flags."
  ) + `<div class="card" id="list"></div>`;

  poll(async () => {
    try {
      $("#list").innerHTML = ridesTable(
        await API.getRides(),
        { people: true }
      );
    } catch {}
  }, C.POLL_MS * 2);
}

// ----------------------------------------------------------
// ADMIN: USERS
// ----------------------------------------------------------
function users() {
  view.innerHTML = head(
    "Users",
    "Passengers and drivers. Block accounts that show repeated fraud."
  ) + `<div class="card" id="list"></div>`;

  const load = async () => {
    try {
      const u = await API.getUsers();

      $("#list").innerHTML = `<div class="table-wrap"><table>
        <thead><tr>
          <th>Name</th><th>Email</th><th>Role</th><th>Rides</th>
          <th>Risk</th><th>Status</th><th></th>
        </tr></thead>
        <tbody>${u.map(x => `<tr>
          <td>${esc(x.name)}</td>
          <td class="muted">${esc(x.email)}</td>
          <td>${esc(x.role)}</td>
          <td>${x.rides}</td>
          <td><span class="chip ${level(x.risk)}">${x.risk}</span></td>
          <td><span class="chip ${esc(x.status)}">${esc(x.status)}</span></td>
          <td>
            <button class="btn ghost sm" data-u="${x.id}"
              data-s="${x.status === "blocked" ? "active" : "blocked"}">
              ${x.status === "blocked" ? "Unblock" : "Block"}
            </button>
          </td>
        </tr>`).join("")}</tbody>
      </table></div>`;

      document.querySelectorAll("[data-u]").forEach(b => {
        b.onclick = async () => {
          await API.setUser(b.dataset.u, b.dataset.s);
          toast("User updated");
          load();
        };
      });
    } catch {}
  };

  load();
}

// ----------------------------------------------------------
// ADMIN: REPORTS
// ----------------------------------------------------------
function reports() {
  view.innerHTML = head(
    "Reports & analytics",
    "Trends from the last 7 days."
  ) + `
    <div class="grid g2">
      <div class="card">
        <div class="card-head"><h2>Rides vs. fraud per day</h2></div>
        <div class="chart-box"><canvas id="c1"></canvas></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Fraud by type</h2></div>
        <div class="chart-box"><canvas id="c2"></canvas></div>
      </div>
    </div>`;

  API.getReports().then(r => {
    if (state.tab !== "reports") return;

    const grid = "rgba(127,214,164,.12)";
    Chart.defaults.color = "#9db5a8";
    Chart.defaults.font.family = "Instrument Sans, system-ui, sans-serif";

    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

    state.charts.push(new Chart($("#c1"), {
      type: "bar",
      data: {
        labels: days,
        datasets: [
          {
            label: "Rides",
            data: r.rides_per_day,
            backgroundColor: "#7fd6a4",
            borderRadius: 6,
            yAxisID: "y"
          },
          {
            label: "Fraud cases",
            data: r.fraud_per_day,
            type: "line",
            borderColor: "#ff5a5f",
            backgroundColor: "#ff5a5f",
            tension: .3,
            yAxisID: "y1"
          }
        ]
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          y: { grid: { color: grid } },
          y1: { position: "right", grid: { display: false } },
          x: { grid: { display: false } }
        }
      }
    }));

    state.charts.push(new Chart($("#c2"), {
      type: "doughnut",
      data: {
        labels: Object.keys(r.fraud_by_type),
        datasets: [{
          data: Object.values(r.fraud_by_type),
          backgroundColor: [
            "#7fd6a4", "#f4c430", "#ff5a5f",
            "#4fa564", "#c98a12", "#b9e6c9"
          ],
          borderWidth: 0
        }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: "right" } }
      }
    }));
  }).catch(() => {});
}

// ----------------------------------------------------------
// BOOT: RESTORE SESSION
// ----------------------------------------------------------
try {
  const u = JSON.parse(localStorage.getItem("rs_user") || "null");
  if (u && API.store.token) start(u);
} catch {}
})();

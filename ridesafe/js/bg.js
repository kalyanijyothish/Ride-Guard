// ============================================================
//  Animated background: a quiet road network with cars drifting along it.
//  Now and then one car turns red and pulses (a flagged ride).
// ============================================================
(() => {
  const cv = document.getElementById("bg");
  if (!cv) return;
  const ctx = cv.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 0, H = 0, dpr = 1, nodes = [], edges = [], cars = [], rings = [];

  const rand = (a, b) => Math.random() * (b - a) + a;

  function build() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const count = Math.max(14, Math.min(34, Math.round((W * H) / 42000)));
    nodes = Array.from({ length: count }, () => ({ x: rand(-20, W + 20), y: rand(-20, H + 20) }));
    edges = [];
    nodes.forEach((n, i) => {
      nodes
        .map((m, j) => ({ j, d: (m.x - n.x) ** 2 + (m.y - n.y) ** 2 }))
        .filter(o => o.j !== i).sort((a, b) => a.d - b.d).slice(0, 2)
        .forEach(o => { if (!edges.some(e => (e[0] === i && e[1] === o.j) || (e[0] === o.j && e[1] === i))) edges.push([i, o.j]); });
    });
    cars = Array.from({ length: Math.round(count * 1.1) }, () => newCar());
    rings = [];
  }

  function newCar() {
    const e = edges[Math.floor(Math.random() * edges.length)];
    const flip = Math.random() < .5;
    return { a: flip ? e[1] : e[0], b: flip ? e[0] : e[1], t: Math.random(), v: rand(.0012, .0034), flag: Math.random() < .07 };
  }

  function frame() {
    ctx.clearRect(0, 0, W, H);

    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(127,214,164,.09)";
    ctx.lineWidth = 10;
    ctx.beginPath();
    edges.forEach(([a, b]) => { ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y); });
    ctx.stroke();
    ctx.strokeStyle = "rgba(127,214,164,.16)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 9]);
    ctx.beginPath();
    edges.forEach(([a, b]) => { ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y); });
    ctx.stroke();
    ctx.setLineDash([]);

    cars.forEach((c, i) => {
      c.t += c.v * (reduce ? 0 : 1);
      if (c.t >= 1) {
        // continue onto a connected road
        const next = edges.filter(e => e[0] === c.b || e[1] === c.b);
        const e = next[Math.floor(Math.random() * next.length)] || edges[0];
        const from = c.b; c.a = from; c.b = e[0] === from ? e[1] : e[0]; c.t = 0;
        if (Math.random() < .05) c.flag = !c.flag && Math.random() < .5;
      }
      const A = nodes[c.a], B = nodes[c.b];
      const x = A.x + (B.x - A.x) * c.t, y = A.y + (B.y - A.y) * c.t;
      if (c.flag && !reduce && Math.random() < .012) rings.push({ x, y, r: 4, life: 1 });
      ctx.fillStyle = c.flag ? "#ff5a5f" : i % 5 === 0 ? "#f4c430" : "#7fd6a4";
      ctx.globalAlpha = c.flag ? .95 : .55;
      ctx.beginPath(); ctx.arc(x, y, c.flag ? 3.2 : 2.4, 0, 6.283); ctx.fill();
    });
    ctx.globalAlpha = 1;

    rings = rings.filter(r => r.life > 0);
    rings.forEach(r => {
      r.r += .55; r.life -= .018;
      ctx.strokeStyle = `rgba(255,90,95,${Math.max(r.life, 0) * .7})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(r.x, r.y, r.r, 0, 6.283); ctx.stroke();
    });

    if (!reduce && !document.hidden) raf = requestAnimationFrame(frame);
  }

  let raf = 0;
  function restart() { cancelAnimationFrame(raf); build(); frame(); }
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(restart, 200); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduce) { cancelAnimationFrame(raf); frame(); } });
  restart();
})();

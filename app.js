const $ = id => document.getElementById(id);
const COLORS = ["#0f766e","#b45309","#4338ca","#be185d","#15803d","#9333ea","#0369a1","#c2410c","#4d7c0f","#7c3aed"];
async function api(url, method = "GET", body) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" },
                               body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { alert(data.detail || "Request failed"); throw new Error(data.detail); }
  return data;
}
const NAMES = { FCFS: "FCFS", SJF: "SJF", PRIORITY: "Priority", RR: "Round Robin" };
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/* ---------------- jobs ---------------- */
async function loadJobs() {
  const jobs = await api("/api/jobs");
  $("jobTable").tBodies[0].innerHTML = jobs.map(j => `<tr><td>${j.id}</td><td>${esc(j.name)}</td>
    <td>${j.arrival}</td><td>${j.burst}</td><td>${j.priority}</td><td>${j.memory} MB</td>
    <td>${esc(j.holds) || "-"}</td><td>${esc(j.waits) || "-"}</td>
    <td><button class="ghost" data-del="${j.id}">Remove</button></td></tr>`).join("")
    || `<tr><td colspan="9" class="empty">No jobs yet. Add one or load the sample jobs.</td></tr>`;
}
$("jobTable").addEventListener("click", async e => {
  if (e.target.dataset.del) { await api("/api/jobs/" + e.target.dataset.del, "DELETE"); loadJobs(); }
});
$("addJob").onclick = async () => {
  if (!$("jobForm").reportValidity()) return;
  await api("/api/jobs", "POST", { name: $("jName").value, arrival: +$("jArr").value,
    burst: +$("jBur").value, priority: +$("jPri").value, memory: +$("jMem").value,
    holds: $("jHold").value, waits: $("jWait").value });
  $("jobForm").reset(); loadJobs();
};
$("sampleJobs").onclick = async () => { await api("/api/jobs/sample", "POST"); loadJobs(); };
$("clearJobs").onclick = async () => { await api("/api/jobs", "DELETE"); loadJobs(); };

/* ---------------- Gantt + playback ---------------- */
const view = { mode: "single", data: null, t: 0, total: 0, timer: null };

function ganttHTML(res, upto, total, title) {
  const pct = x => (x / total * 100) + "%";
  const color = id => COLORS[(id - 1) % COLORS.length];
  const rows = res.jobs.map(j => {
    const mine = res.slices.filter(s => s.job_id === j.id);
    let html = "", cursor = j.arrival;
    const end = j.finish_time ?? total;
    const waitSeg = (a, b) => { b = Math.min(b, upto); if (b > a)
      html += `<div class="blk wait" style="left:${pct(a)};width:${pct(b - a)}"></div>`; };
    mine.forEach(s => { waitSeg(cursor, s.start); cursor = s.end;
      const e = Math.min(s.end, upto);
      if (e > s.start) html += `<div class="blk" style="left:${pct(s.start)};width:${pct(e - s.start)};background:${color(j.id)}">${esc(j.name)}</div>`; });
    waitSeg(cursor, end);
    if (j.finish_time != null && j.finish_time <= upto)
      html += `<div class="fin-mark" style="left:${pct(j.finish_time)}"></div>`;
    return `<div class="row"><div class="lab" title="${esc(j.name)}">${esc(j.name)} (arr ${j.arrival})</div><div class="track" style="--unit:${100 / total}%">${html}</div></div>`;
  }).join("");
  const idle = res.slices.filter(s => s.kind === "IDLE").map(s => {
    const e = Math.min(s.end, upto);
    return e > s.start ? `<div class="blk idle" style="left:${pct(s.start)};width:${pct(e - s.start)}"></div>` : "";
  }).join("");
  const sw = res.events.filter(e => e.type === "SWITCH" && e.time <= upto)
    .map(e => `<div class="sw-line" style="left:${pct(e.time)}" title="switch at t=${e.time}: ${esc(e.detail)}"></div>`).join("");
  const step = total > 40 ? Math.ceil(total / 20) : 1;
  let ticks = "";
  for (let i = 0; i <= total; i += step) ticks += `<span style="left:${pct(i)}">${i}</span>`;
  const cur = `<div class="cursor" style="left:${pct(upto)}"></div>`;
  return `<div class="gantt">${title ? `<h3>${title}</h3>` : ""}
    <div style="position:relative">${rows}
      <div class="row"><div class="lab">CPU idle</div><div class="track" style="--unit:${100 / total}%">${idle}</div></div>
      <div style="position:absolute;left:110px;right:0;top:0;bottom:0;pointer-events:none">${sw}${cur}</div>
    </div><div class="axis" style="margin-left:110px">${ticks}</div></div>`;
}

function metricsTable(res) {
  const rows = res.jobs.map(j => `<tr><td>${esc(j.name)}</td><td>${j.arrival}</td><td>${j.burst}</td>
    <td>${j.start_time ?? "-"}</td><td>${j.finish_time ?? "-"}</td><td>${j.waiting ?? "-"}</td><td>${j.turnaround ?? "-"}</td></tr>`).join("");
  const m = res.metrics;
  return `<table><thead><tr><th>Job</th><th>Arrival</th><th>CPU</th><th>Start</th><th>Finish</th><th>Waiting</th><th>Turnaround</th></tr></thead><tbody>${rows}</tbody></table>
  <p class="hint">Average waiting ${m.avg_waiting} · average turnaround ${m.avg_turnaround} · CPU busy ${m.cpu_utilization}% · idle ${m.idle_time} · switches ${m.switches}</p>`;
}

function compareTable(all) {
  const rows = Object.entries(all).map(([a, r]) => `<tr><td>${NAMES[a]}</td><td>${r.metrics.avg_waiting}</td>
    <td>${r.metrics.avg_turnaround}</td><td>${r.metrics.avg_response}</td><td>${r.metrics.cpu_utilization}%</td>
    <td>${r.metrics.idle_time}</td><td>${r.metrics.switches}</td></tr>`).join("");
  return `<table><thead><tr><th>Rule</th><th>Avg waiting</th><th>Avg turnaround</th><th>Avg response</th><th>CPU busy</th><th>Idle</th><th>Switches</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function render() {
  const d = view.data;
  if (!d) return;
  $("scrub").max = view.total; $("scrub").value = view.t;
  $("clock").textContent = `t = ${view.t} / ${view.total}`;
  if (view.mode === "compare") {
    $("view").innerHTML = Object.entries(d).map(([a, r]) => ganttHTML(r, view.t, view.total, NAMES[a])).join("");
    $("metrics").innerHTML = compareTable(d);
  } else {
    $("view").innerHTML = ganttHTML(d, view.t, view.total, `${NAMES[d.algorithm]}${d.algorithm === "RR" ? " (slice " + d.quantum + ")" : ""}${d.run_id ? " · run #" + d.run_id : ""}`);
    $("metrics").innerHTML = metricsTable(d);
  }
}
function totalOf(res) { return Math.max(1, ...res.slices.map(s => s.end)); }
function setView(mode, data, t = null) {
  stop();
  view.mode = mode; view.data = data;
  view.total = mode === "compare" ? Math.max(...Object.values(data).map(totalOf)) : totalOf(data);
  view.t = t === null ? view.total : t;
  render();
}
function stop() { clearInterval(view.timer); view.timer = null; $("bPlay").textContent = "Play"; }
function play() {
  if (view.timer) return stop();
  if (view.t >= view.total) view.t = 0;
  $("bPlay").textContent = "Pause";
  view.timer = setInterval(() => { if (view.t >= view.total) return stop(); view.t++; render(); }, +$("speed").value);
}
$("bPlay").onclick = play;
$("bNext").onclick = () => { stop(); view.t = Math.min(view.total, view.t + 1); render(); };
$("bPrev").onclick = () => { stop(); view.t = Math.max(0, view.t - 1); render(); };
$("bReset").onclick = () => { stop(); view.t = 0; render(); };
$("bEnd").onclick = () => { stop(); view.t = view.total; render(); };
$("scrub").oninput = e => { stop(); view.t = +e.target.value; render(); };
$("speed").onchange = () => { if (view.timer) { stop(); play(); } };

$("runBtn").onclick = async () => {
  const data = await api("/api/simulate", "POST", { algorithm: $("algo").value, quantum: +$("quantum").value });
  setView("single", data, 0); loadRuns(); play();
};
$("compareBtn").onclick = async () => {
  const data = await api("/api/compare?quantum=" + (+$("quantum").value || 2), "POST");
  setView("compare", data, 0); play();
};

/* ---------------- history ---------------- */
async function loadRuns() {
  const runs = await api("/api/runs");
  $("runTable").tBodies[0].innerHTML = runs.map(r => `<tr><td>#${r.id}</td><td>${NAMES[r.algorithm]}</td>
    <td><span class="tag ${r.status}">${r.status}</span></td><td>${r.sim_time}</td><td>${r.created_at}</td>
    <td><button class="ghost" data-open="${r.id}">Open</button> <button data-replay="${r.id}">Replay</button></td></tr>`).join("")
    || `<tr><td colspan="6" class="empty">No saved runs yet.</td></tr>`;
}
$("runTable").addEventListener("click", async e => {
  const open = e.target.dataset.open, rp = e.target.dataset.replay;
  if (!open && !rp) return;
  const data = await api("/api/runs/" + (open || rp));
  setView("single", data, rp ? 0 : null);
  if (rp) play();
  $("timeline").scrollIntoView({ behavior: "smooth" });
});

/* ---------------- live run, crash and recovery ---------------- */
function showLive(d) {
  const un = d.unfinished || [];
  if (!d.active) {
    $("monitor").innerHTML = "";
    $("liveMsg").textContent = un.length
      ? `Live run is not in memory. Run #${un[0].id} (${NAMES[un[0].algorithm]}) is unfinished at t=${un[0].sim_time} in the database. Use “Recover from database”.`
      : "No live run. Choose “Start live run”, then step through it.";
    return;
  }
  const s = d.snapshot, pct = Math.round(100 * s.memory_used / s.memory_total);
  $("liveMsg").textContent = d.status === "FINISHED" ? "Run finished and saved." : `Run #${d.run_id} · ${NAMES[d.algorithm]} · t=${s.time}`;
  $("monitor").innerHTML = `<p>Memory ${s.memory_used} / ${s.memory_total} MB used (${s.memory_free} MB left)</p>
    <div class="mem"><i style="width:${pct}%"></i></div>
    <p>CPU now ${s.cpu_percent}% · overall busy ${s.cpu_utilization}% · running: ${s.current ? esc(d.jobs.find(j => j.id === s.current)?.name) : "none"}</p>
    <table><thead><tr><th>Job</th><th>Status</th><th>Remaining</th><th>Memory</th></tr></thead><tbody>${
      d.jobs.map(j => `<tr><td>${esc(j.name)}</td><td><span class="tag ${j.status}">${j.status}</span></td><td>${j.remaining}</td>
      <td>${s.per_job.some(p => p.id === j.id) ? j.memory + " MB" : "-"}</td></tr>`).join("")}</tbody></table>`;
  setView("single", d);
}
const live = (path, body) => api("/api/live" + path, "POST", body).then(d => { showLive(d); loadRuns(); });
$("lStart").onclick = () => live("/start", { algorithm: $("algo").value, quantum: +$("quantum").value });
$("lStep").onclick = () => live("/step", { n: 1 });
$("lStep5").onclick = () => live("/step", { n: 5 });
$("lCrash").onclick = () => { live("/crash"); };
$("lRecover").onclick = () => live("/recover");

/* ---------------- deadlock (graph built from the jobs' Holds / Waits-for) ---------------- */
function drawGraph(graph, edges, cycle) {
  const nodes = Object.keys(graph);
  if (!nodes.length) return `<p class="empty">No jobs to draw.</p>`;
  const W = 560, H = 360, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 55, r = 26;
  const pos = {};
  nodes.forEach((n, i) => {
    const a = 2 * Math.PI * i / nodes.length - Math.PI / 2;
    pos[n] = nodes.length === 1 ? [cx, cy] : [cx + R * Math.cos(a), cy + R * Math.sin(a)];
  });
  const bad = new Set(), inCycle = new Set(cycle || []);
  for (let i = 0; cycle && i < cycle.length - 1; i++) bad.add(cycle[i] + ">" + cycle[i + 1]);
  const paths = edges.map(e => {
    const [x1, y1] = pos[e.from], [x2, y2] = pos[e.to];
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
    const sx = x1 + ux * r, sy = y1 + uy * r, ex = x2 - ux * (r + 5), ey = y2 - uy * (r + 5);
    const mx = (sx + ex) / 2 - uy * 24, my = (sy + ey) / 2 + ux * 24;
    const lx = .25 * sx + .5 * mx + .25 * ex, ly = .25 * sy + .5 * my + .25 * ey;
    const red = bad.has(e.from + ">" + e.to), col = red ? "var(--red)" : "var(--mute)";
    return `<path d="M${sx},${sy} Q${mx},${my} ${ex},${ey}" fill="none" style="stroke:${col}" stroke-width="2" marker-end="url(#${red ? "ahr" : "ah"})"/>
      <text x="${lx}" y="${ly - 4}" text-anchor="middle" font-size="12" style="fill:${col}">${esc(e.resource)}</text>`;
  }).join("");
  const circles = nodes.map(n => `<circle cx="${pos[n][0]}" cy="${pos[n][1]}" r="${r}" style="fill:var(--card);stroke:${inCycle.has(n) ? "var(--red)" : "var(--teal)"}" stroke-width="2.5"/>
    <text x="${pos[n][0]}" y="${pos[n][1] + 4}" text-anchor="middle" font-size="12" style="fill:var(--ink)">${esc(n.length > 8 ? n.slice(0, 7) + "…" : n)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Wait-for graph">
    <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" style="fill:var(--mute)"/></marker>
    <marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" style="fill:var(--red)"/></marker></defs>
    ${paths}${circles}</svg>`;
}
function graphText(r) {
  const lines = r.edges.map(e => `${e.from} waits for ${e.to}  (${e.to} holds ${e.resource})`);
  return (lines.length ? lines.join("\n") : "No job is waiting for a resource held by another job.");
}
$("dlDetect").onclick = async () => {
  const r = await api("/api/deadlock/detect", "POST");
  $("dlGraph").innerHTML = drawGraph(r.graph, r.edges, r.cycle);
  $("dlOut").textContent = graphText(r) + "\n\n" +
    (r.cycle ? "DEADLOCK found: " + r.cycle.join(" -> ") : "No deadlock.");
};
$("dlRecover").onclick = async () => {
  const r = await api("/api/deadlock/recover", "POST");
  $("dlGraph").innerHTML = drawGraph(r.graph, r.edges, null);
  $("dlOut").textContent = r.steps.length
    ? r.steps.map(s => `Loop ${s.cycle.join(" -> ")}: stopped ${s.victim}, freed ${s.released.join(", ") || "nothing"}`).join("\n") +
      "\n\nStopped jobs were removed from the job list. Remaining jobs: " + (r.remaining.map(p => p.id).join(", ") || "none")
    : "No deadlock, nothing to recover.";
  loadJobs();
};
$("dlExample").onclick = async () => { await api("/api/jobs/deadlock-example", "POST"); await loadJobs(); $("dlDetect").click(); };

/* ---------------- start ---------------- */
loadJobs(); loadRuns();
api("/api/live").then(showLive);

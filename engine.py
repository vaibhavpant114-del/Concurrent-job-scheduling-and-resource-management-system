"""Scheduling engine: advances a simulated CPU one time unit per tick.

Supports FCFS, SJF, PRIORITY (lower number = more urgent) and RR.
Memory is simulated: a job takes its memory when it first starts and gives
it back when it finishes. A job that does not fit has to WAIT.
"""
TOTAL_MEMORY = 1024  # simulated MB
ALGORITHMS = ["FCFS", "SJF", "PRIORITY", "RR"]


class Engine:
    def __init__(self, jobs, algorithm="FCFS", quantum=2, total_memory=TOTAL_MEMORY):
        self.algorithm = algorithm.upper()
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"Unknown algorithm {algorithm}")
        self.quantum = max(1, int(quantum))
        self.total_memory = total_memory
        # every engine works on its OWN copy of the jobs
        self.jobs = {
            j["id"]: {
                "id": j["id"], "name": j["name"], "arrival": j["arrival"],
                "burst": j["burst"], "priority": j["priority"], "memory": j["memory"],
                "remaining": j["burst"], "status": "NEW",
                "start_time": None, "finish_time": None, "held": False,
            } for j in jobs
        }
        self.time = 0
        self.current = None
        self.queue = []
        self.slice_used = 0
        self.last_run = None
        self.busy = 0
        self.blocked = set()
        self.events, self.changes, self.res_events = [], [], []
        self._f = [0, 0, 0]  # how much has already been saved

    # ---------- helpers ----------
    @property
    def memory_used(self):
        return sum(j["memory"] for j in self.jobs.values() if j["held"])

    def _log(self, type_, job_id=None, detail="", t=None):
        self.events.append({"time": self.time if t is None else t, "type": type_,
                            "job_id": job_id, "detail": detail})

    def _set(self, job, status):
        if job["status"] != status:
            self.changes.append({"time": self.time, "job_id": job["id"],
                                 "old": job["status"], "new": status})
            job["status"] = status

    def _res(self, job, action):
        used = self.memory_used
        self.res_events.append({"time": self.time, "job_id": job["id"], "action": action,
                                "memory_used": used, "memory_free": self.total_memory - used})

    def done(self):
        return all(j["status"] == "FINISHED" for j in self.jobs.values())

    def _arrivals(self):
        for j in sorted(self.jobs.values(), key=lambda x: x["id"]):
            if j["status"] == "NEW" and j["arrival"] <= self.time:
                self._set(j, "READY")
                self.queue.append(j["id"])
                self._log("ARRIVE", j["id"], t=j["arrival"])

    def _pick(self):
        free = self.total_memory - self.memory_used
        ok = []
        for jid in self.queue:
            j = self.jobs[jid]
            if j["held"] or j["memory"] <= free:
                ok.append(jid)
            elif jid not in self.blocked:
                self.blocked.add(jid)
                self._set(j, "WAITING")
                self._log("WAIT", jid, f"needs {j['memory']} MB, only {free} MB free")
        if not ok:
            return None
        J = self.jobs
        if self.algorithm == "FCFS":
            pick = min(ok, key=lambda i: (J[i]["arrival"], i))
        elif self.algorithm == "SJF":
            pick = min(ok, key=lambda i: (J[i]["burst"], J[i]["arrival"], i))
        elif self.algorithm == "PRIORITY":
            pick = min(ok, key=lambda i: (J[i]["priority"], J[i]["arrival"], i))
        else:
            pick = ok[0]
        self.queue.remove(pick)
        self.blocked.discard(pick)
        return pick

    # ---------- one tick ----------
    def tick(self):
        self._arrivals()
        if self.current is None:
            self.current = self._pick()
            if self.current is not None:
                j = self.jobs[self.current]
                if not j["held"]:
                    j["held"] = True
                    self._res(j, "ALLOCATE")
                if self.last_run is not None and self.last_run != self.current:
                    self._log("SWITCH", self.current, f"{self.last_run} -> {self.current}")
                if j["start_time"] is None:
                    j["start_time"] = self.time
                    self._log("START", self.current)
                else:
                    self._log("RESUME", self.current)
                self._set(j, "RUNNING")
                self.slice_used = 0
        if self.current is None:
            self._log("IDLE")
            self.time += 1
            return
        j = self.jobs[self.current]
        self._log("RUN", j["id"])
        j["remaining"] -= 1
        self.last_run = j["id"]
        self.slice_used += 1
        self.busy += 1
        self.time += 1
        if j["remaining"] == 0:
            j["finish_time"] = self.time
            self._set(j, "FINISHED")
            j["held"] = False
            self._res(j, "RELEASE")
            self._log("FINISH", j["id"])
            self.current = None
        elif self.algorithm == "RR" and self.slice_used >= self.quantum:
            self._arrivals()  # new arrivals queue before the preempted job
            self._set(j, "READY")
            self.queue.append(j["id"])
            self._log("PREEMPT", j["id"], "quantum used up")
            self.current = None

    def run_all(self, limit=5000):
        while not self.done() and self.time < limit:
            self.tick()
        return self

    # ---------- save / restore ----------
    def pending(self):
        """Return everything produced since the last call (to be saved together)."""
        out = (self.events[self._f[0]:], self.changes[self._f[1]:], self.res_events[self._f[2]:])
        self._f = [len(self.events), len(self.changes), len(self.res_events)]
        return out

    def state(self):
        return {"time": self.time, "current": self.current, "queue": self.queue,
                "slice_used": self.slice_used, "last_run": self.last_run, "busy": self.busy,
                "blocked": sorted(self.blocked)}

    @classmethod
    def restore(cls, jobs_rows, algorithm, quantum, state, total_memory=TOTAL_MEMORY):
        eng = cls(jobs_rows, algorithm, quantum, total_memory)
        for r in jobs_rows:
            j = eng.jobs[r["id"]]
            j["remaining"], j["status"] = r["remaining"], r["status"]
            j["start_time"], j["finish_time"] = r["start_time"], r["finish_time"]
            # resource numbers are REBUILT from the unfinished jobs that had started
            j["held"] = r["start_time"] is not None and r["status"] != "FINISHED"
        eng.time, eng.current = state["time"], state["current"]
        eng.queue, eng.slice_used = list(state["queue"]), state["slice_used"]
        eng.last_run, eng.busy = state["last_run"], state["busy"]
        eng.blocked = set(state["blocked"])
        return eng

    def snapshot(self):
        used = self.memory_used
        return {"time": self.time, "memory_total": self.total_memory, "memory_used": used,
                "memory_free": self.total_memory - used,
                "cpu_percent": 100 if self.current is not None else 0,
                "cpu_utilization": round(100 * self.busy / self.time, 1) if self.time else 0,
                "current": self.current,
                "per_job": [{"id": j["id"], "name": j["name"], "memory": j["memory"]}
                            for j in self.jobs.values() if j["held"]]}


# ---------- results ----------
def slices_from_events(events):
    out = []
    for e in events:
        if e["type"] not in ("RUN", "IDLE"):
            continue
        job = e["job_id"] if e["type"] == "RUN" else None
        if out and out[-1]["job_id"] == job and out[-1]["end"] == e["time"]:
            out[-1]["end"] = e["time"] + 1
        else:
            out.append({"job_id": job, "start": e["time"], "end": e["time"] + 1,
                        "kind": "RUN" if job is not None else "IDLE"})
    return out


def compute_metrics(jobs, events):
    fin = [j for j in jobs if j["finish_time"] is not None]
    n = len(fin) or 1
    tat = [j["finish_time"] - j["arrival"] for j in fin]
    wait = [t - j["burst"] for t, j in zip(tat, fin)]
    resp = [j["start_time"] - j["arrival"] for j in fin]
    busy = sum(1 for e in events if e["type"] == "RUN")
    idle = sum(1 for e in events if e["type"] == "IDLE")
    total = busy + idle
    return {"avg_waiting": round(sum(wait) / n, 2), "avg_turnaround": round(sum(tat) / n, 2),
            "avg_response": round(sum(resp) / n, 2),
            "cpu_utilization": round(100 * busy / total, 1) if total else 0,
            "idle_time": idle, "switches": sum(1 for e in events if e["type"] == "SWITCH"),
            "total_time": total}


def build_result(eng, events=None):
    events = eng.events if events is None else events
    jobs = []
    for j in sorted(eng.jobs.values(), key=lambda x: x["id"]):
        d = {k: j[k] for k in ("id", "name", "arrival", "burst", "priority", "memory",
                               "remaining", "status", "start_time", "finish_time")}
        if d["finish_time"] is not None:
            d["turnaround"] = d["finish_time"] - d["arrival"]
            d["waiting"] = d["turnaround"] - d["burst"]
        jobs.append(d)
    return {"algorithm": eng.algorithm, "quantum": eng.quantum, "jobs": jobs, "events": events,
            "slices": slices_from_events(events), "metrics": compute_metrics(jobs, events)}

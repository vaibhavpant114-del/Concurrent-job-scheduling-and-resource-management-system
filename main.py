"""FastAPI app: jobs, simulation, comparison, history/replay, live run with crash recovery,
and deadlock tools.  Run with:  uvicorn backend.main:app --reload"""
import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import storage, deadlock
from .engine import Engine, ALGORITHMS, TOTAL_MEMORY, build_result

app = FastAPI(title="Concurrent Job Scheduling and Resource Management System")
FRONT = os.path.join(os.path.dirname(__file__), "..", "frontend")

LIVE = {"engine": None, "run_id": None}   # in-memory state; lost on a simulated crash


@app.on_event("startup")
def startup():
    storage.init_db()


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    arrival: int = Field(ge=0)
    burst: int = Field(ge=1)
    priority: int = Field(ge=1)
    memory: int = Field(ge=1)
    holds: str = Field(default="", max_length=200)   # resources this job holds, e.g. "R1,R2"
    waits: str = Field(default="", max_length=200)   # resources this job waits for, e.g. "R3"


class RunIn(BaseModel):
    algorithm: str = "FCFS"
    quantum: int = Field(default=2, ge=1)


class StepIn(BaseModel):
    n: int = Field(default=1, ge=1, le=500)


def _split(text):
    return [x.strip() for x in (text or "").replace(";", ",").split(",") if x.strip()]


def _procs():
    """Turn the job table (Holds / Waits-for columns) into processes for the wait-for graph."""
    jobs = storage.list_jobs()
    names = [j["name"] for j in jobs]
    out = []
    for j in jobs:
        label = j["name"] if names.count(j["name"]) == 1 else f"{j['name']}#{j['id']}"
        out.append({"id": label, "job_id": j["id"],
                    "holds": _split(j.get("holds")), "waits": _split(j.get("waits"))})
    return out


def _jobs_or_400():
    jobs = storage.list_jobs()
    if not jobs:
        raise HTTPException(400, "Add at least one job first.")
    res = deadlock.detect(_procs())
    if res["cycle"]:   # deadlocked jobs can never finish, so do not simulate them
        raise HTTPException(409, "Deadlock among jobs: " + " -> ".join(res["cycle"]) +
                            ". Open 'Deadlock check' and recover first.")
    return jobs


# ---------- jobs ----------
@app.get("/api/jobs")
def get_jobs():
    return storage.list_jobs()


@app.post("/api/jobs")
def post_job(j: JobIn):
    if j.memory > TOTAL_MEMORY:
        raise HTTPException(400, f"Memory need cannot be more than {TOTAL_MEMORY} MB.")
    d = j.model_dump()
    d["holds"], d["waits"] = ", ".join(_split(d["holds"])), ", ".join(_split(d["waits"]))
    return storage.add_job(d)


@app.delete("/api/jobs/{job_id}")
def del_job(job_id: int):
    storage.delete_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/sample")
def sample_jobs():
    return storage.seed_sample()


@app.post("/api/jobs/deadlock-example")
def deadlock_example():
    return storage.seed_deadlock_example()


@app.delete("/api/jobs")
def clear_jobs():
    storage.clear_jobs()
    return {"ok": True}


# ---------- full simulation, history, comparison ----------
@app.post("/api/simulate")
def simulate(r: RunIn):
    if r.algorithm.upper() not in ALGORITHMS:
        raise HTTPException(400, "Unknown algorithm.")
    eng = Engine(_jobs_or_400(), r.algorithm, r.quantum).run_all()
    run_id = storage.create_run(eng, save_now=True)      # one transaction
    return storage.load_run(run_id)


@app.post("/api/compare")
def compare(quantum: int = 2):
    jobs = _jobs_or_400()
    return {a: build_result(Engine(jobs, a, quantum).run_all()) for a in ALGORITHMS}


@app.get("/api/runs")
def runs():
    return storage.list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int):
    data = storage.load_run(run_id)
    if not data:
        raise HTTPException(404, "Run not found.")
    return data


# ---------- live run + crash recovery ----------
def _live_view():
    eng, rid = LIVE["engine"], LIVE["run_id"]
    if eng is None:
        return {"active": False, "unfinished": storage.find_unfinished()}
    data = storage.load_run(rid)
    data.update({"active": True, "snapshot": eng.snapshot(), "queue": eng.queue,
                 "unfinished": storage.find_unfinished()})
    return data


@app.get("/api/live")
def live():
    return _live_view()


@app.post("/api/live/start")
def live_start(r: RunIn):
    eng = Engine(_jobs_or_400(), r.algorithm, r.quantum)
    LIVE["engine"], LIVE["run_id"] = eng, storage.create_run(eng)
    return _live_view()


@app.post("/api/live/step")
def live_step(s: StepIn):
    eng = LIVE["engine"]
    if eng is None:
        raise HTTPException(409, "No live run. Start one, or recover after a crash.")
    for _ in range(s.n):
        if eng.done():
            break
        eng.tick()
        storage.save_step(LIVE["run_id"], eng)
    return _live_view()


@app.post("/api/live/crash")
def live_crash():
    if LIVE["engine"] is None:
        raise HTTPException(409, "No live run to crash.")
    storage.add_event(LIVE["run_id"], "CRASH", "simulated crash: memory state lost")
    LIVE["engine"] = LIVE["run_id"] = None
    return _live_view()


@app.post("/api/live/recover")
def live_recover():
    unfinished = storage.find_unfinished()
    if not unfinished:
        raise HTTPException(404, "No unfinished run found in the database.")
    rid = unfinished[0]["id"]
    saved = storage.load_run(rid)
    eng = Engine.restore(saved["jobs"], saved["algorithm"], saved["quantum"], saved["state"])
    LIVE["engine"], LIVE["run_id"] = eng, rid
    storage.add_event(rid, "RECOVER",
                      f"restored {sum(1 for j in saved['jobs'] if j['status'] != 'FINISHED')} "
                      f"unfinished job(s); memory in use {eng.memory_used} MB")
    return _live_view()


# ---------- deadlock (built from the Holds / Waits-for columns of the jobs) ----------
@app.post("/api/deadlock/detect")
def dl_detect():
    res = deadlock.detect(_procs())
    if res["cycle"] and LIVE["run_id"]:
        storage.add_event(LIVE["run_id"], "DEADLOCK", " -> ".join(res["cycle"]))
    return res


@app.post("/api/deadlock/recover")
def dl_recover():
    procs = _procs()
    id_of = {p["id"]: p["job_id"] for p in procs}
    res = deadlock.recover(procs)
    res["stopped"] = [s["victim"] for s in res["steps"]]
    for s in res["steps"]:                       # stop the victim: remove it, freeing its resources
        storage.delete_job(id_of[s["victim"]])
    if res["steps"] and LIVE["run_id"]:
        storage.add_event(LIVE["run_id"], "RECOVERY",
                          ", ".join(f"stopped {v}" for v in res["stopped"]))
    return res


# ---------- frontend ----------
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONT, "index.html"))


app.mount("/static", StaticFiles(directory=FRONT), name="static")

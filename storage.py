"""Database layer (PostgreSQL or SQLite through SQLAlchemy).

Related changes (job status + resources + events + run state) are always saved
inside ONE transaction, so saved data never shows half of a change.
"""
import os
import json
import datetime
from dotenv import load_dotenv
from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Text,
                        DateTime, ForeignKey, select, insert, update, delete, func,
                        inspect, text)
from .engine import slices_from_events, compute_metrics

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobsched.db")
db = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
meta = MetaData()

jobs_t = Table("jobs", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(60), nullable=False), Column("arrival", Integer, nullable=False),
    Column("burst", Integer, nullable=False), Column("priority", Integer, nullable=False),
    Column("memory", Integer, nullable=False),
    Column("holds", String(200), nullable=False, default="", server_default=""),
    Column("waits", String(200), nullable=False, default="", server_default=""))
runs_t = Table("runs", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("algorithm", String(10), nullable=False), Column("quantum", Integer, nullable=False),
    Column("status", String(12), nullable=False), Column("sim_time", Integer, default=0),
    Column("state_json", Text, default="{}"), Column("created_at", DateTime, nullable=False))
run_jobs_t = Table("run_jobs", meta,
    Column("run_id", Integer, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("job_id", Integer, primary_key=True), Column("name", String(60)),
    Column("arrival", Integer), Column("burst", Integer), Column("priority", Integer),
    Column("memory", Integer), Column("remaining", Integer), Column("status", String(12)),
    Column("start_time", Integer), Column("finish_time", Integer))
events_t = Table("run_events", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("runs.id", ondelete="CASCADE")),
    Column("seq", Integer, nullable=False), Column("time", Integer, nullable=False),
    Column("type", String(12), nullable=False), Column("job_id", Integer), Column("detail", Text))
changes_t = Table("status_changes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("runs.id", ondelete="CASCADE")),
    Column("job_id", Integer), Column("time", Integer),
    Column("old_status", String(12)), Column("new_status", String(12)))
res_t = Table("resource_events", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("runs.id", ondelete="CASCADE")),
    Column("job_id", Integer), Column("time", Integer), Column("action", String(12)),
    Column("memory_used", Integer), Column("memory_free", Integer))


def init_db():
    meta.create_all(db)
    # older databases (before the Holds / Waits-for columns existed) are upgraded in place
    cols = {c["name"] for c in inspect(db).get_columns("jobs")}
    with db.begin() as c:
        for col in ("holds", "waits"):
            if col not in cols:
                c.execute(text(f"ALTER TABLE jobs ADD COLUMN {col} VARCHAR(200) NOT NULL DEFAULT ''"))


def _rows(conn, q):
    return [dict(r._mapping) for r in conn.execute(q)]


# ---------- job catalogue ----------
def list_jobs():
    with db.connect() as c:
        return _rows(c, select(jobs_t).order_by(jobs_t.c.id))


def add_job(d):
    with db.begin() as c:
        new_id = c.execute(insert(jobs_t).values(**d)).inserted_primary_key[0]
    return {"id": new_id, **d}


def delete_job(job_id):
    with db.begin() as c:
        c.execute(delete(jobs_t).where(jobs_t.c.id == job_id))


def clear_jobs():
    with db.begin() as c:
        c.execute(delete(jobs_t))


SAMPLE = [("Compiler", 0, 6, 3, 200), ("Editor", 1, 3, 1, 120), ("Backup", 2, 8, 4, 300),
          ("Browser", 3, 2, 2, 250), ("Report", 12, 3, 2, 100)]


def seed_sample():
    clear_jobs()
    with db.begin() as c:
        for n, a, b, p, m in SAMPLE:
            c.execute(insert(jobs_t).values(name=n, arrival=a, burst=b, priority=p, memory=m))
    return list_jobs()


DEADLOCK_EXAMPLE = [  # name, arrival, burst, priority, memory, holds, waits
    ("Editor", 0, 3, 1, 100, "R1", "R2"), ("Compiler", 1, 4, 2, 150, "R2", "R3"),
    ("Backup", 2, 5, 3, 200, "R3", "R1"), ("Browser", 3, 2, 2, 120, "R4", "")]


def seed_deadlock_example():
    clear_jobs()
    with db.begin() as c:
        for n, a, b, p, m, h, w in DEADLOCK_EXAMPLE:
            c.execute(insert(jobs_t).values(name=n, arrival=a, burst=b, priority=p,
                                            memory=m, holds=h, waits=w))
    return list_jobs()


# ---------- runs ----------
def _save_pending(c, run_id, eng):
    """Write everything new since the last save. Caller owns the transaction."""
    events, changes, res = eng.pending()
    seq = c.execute(select(func.coalesce(func.max(events_t.c.seq), 0))
                    .where(events_t.c.run_id == run_id)).scalar()
    for e in events:
        seq += 1
        c.execute(insert(events_t).values(run_id=run_id, seq=seq, time=e["time"], type=e["type"],
                                          job_id=e["job_id"], detail=e["detail"]))
    for ch in changes:
        c.execute(insert(changes_t).values(run_id=run_id, job_id=ch["job_id"], time=ch["time"],
                                           old_status=ch["old"], new_status=ch["new"]))
    for r in res:
        c.execute(insert(res_t).values(run_id=run_id, **r))
    for j in eng.jobs.values():
        c.execute(update(run_jobs_t).where((run_jobs_t.c.run_id == run_id) &
                  (run_jobs_t.c.job_id == j["id"]))
                  .values(remaining=j["remaining"], status=j["status"],
                          start_time=j["start_time"], finish_time=j["finish_time"]))
    c.execute(update(runs_t).where(runs_t.c.id == run_id).values(
        sim_time=eng.time, state_json=json.dumps(eng.state()),
        status="FINISHED" if eng.done() else "RUNNING"))


def create_run(eng, save_now=False):
    """Create a run and its job rows. With save_now=True also save all engine output."""
    with db.begin() as c:
        run_id = c.execute(insert(runs_t).values(
            algorithm=eng.algorithm, quantum=eng.quantum, status="RUNNING", sim_time=0,
            state_json="{}", created_at=datetime.datetime.utcnow())).inserted_primary_key[0]
        for j in eng.jobs.values():
            c.execute(insert(run_jobs_t).values(
                run_id=run_id, job_id=j["id"], name=j["name"], arrival=j["arrival"],
                burst=j["burst"], priority=j["priority"], memory=j["memory"],
                remaining=j["remaining"], status=j["status"],
                start_time=j["start_time"], finish_time=j["finish_time"]))
        if save_now:
            _save_pending(c, run_id, eng)
    return run_id


def save_step(run_id, eng):
    with db.begin() as c:  # ONE transaction per step
        _save_pending(c, run_id, eng)


def add_event(run_id, type_, detail="", time=None):
    with db.begin() as c:
        run = c.execute(select(runs_t).where(runs_t.c.id == run_id)).mappings().first()
        seq = c.execute(select(func.coalesce(func.max(events_t.c.seq), 0))
                        .where(events_t.c.run_id == run_id)).scalar() + 1
        c.execute(insert(events_t).values(run_id=run_id, seq=seq,
                  time=run["sim_time"] if time is None else time, type=type_,
                  job_id=None, detail=detail))


def list_runs():
    with db.connect() as c:
        rs = _rows(c, select(runs_t).order_by(runs_t.c.id.desc()).limit(50))
    for r in rs:
        r.pop("state_json", None)
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    return rs


def load_run(run_id):
    with db.connect() as c:
        run = c.execute(select(runs_t).where(runs_t.c.id == run_id)).mappings().first()
        if not run:
            return None
        jobs = _rows(c, select(run_jobs_t).where(run_jobs_t.c.run_id == run_id)
                     .order_by(run_jobs_t.c.job_id))
        events = _rows(c, select(events_t).where(events_t.c.run_id == run_id)
                       .order_by(events_t.c.seq))
    for j in jobs:
        j["id"] = j.pop("job_id")
        if j["finish_time"] is not None:
            j["turnaround"] = j["finish_time"] - j["arrival"]
            j["waiting"] = j["turnaround"] - j["burst"]
    for e in events:
        e.pop("id", None)
        e.pop("run_id", None)
    return {"run_id": run_id, "algorithm": run["algorithm"], "quantum": run["quantum"],
            "status": run["status"], "sim_time": run["sim_time"],
            "state": json.loads(run["state_json"] or "{}"),
            "jobs": jobs, "events": events, "slices": slices_from_events(events),
            "metrics": compute_metrics(jobs, events)}


def find_unfinished():
    with db.connect() as c:
        return _rows(c, select(runs_t.c.id, runs_t.c.algorithm, runs_t.c.sim_time)
                     .where(runs_t.c.status == "RUNNING").order_by(runs_t.c.id.desc()))

from backend.engine import Engine, build_result
from backend import deadlock

JOBS = [
    {"id": 1, "name": "A", "arrival": 0, "burst": 5, "priority": 3, "memory": 100},
    {"id": 2, "name": "B", "arrival": 1, "burst": 3, "priority": 1, "memory": 100},
    {"id": 3, "name": "C", "arrival": 2, "burst": 1, "priority": 2, "memory": 100},
]


def order(algo, q=2):
    r = build_result(Engine(JOBS, algo, q).run_all())
    return [s["job_id"] for s in r["slices"] if s["kind"] == "RUN"]


def test_fcfs():
    assert order("FCFS") == [1, 2, 3]


def test_sjf():
    assert order("SJF") == [1, 3, 2]


def test_priority():
    assert order("PRIORITY") == [1, 2, 3]


def test_rr_slices():
    assert order("RR", 2) == [1, 2, 3, 1, 2, 1]


def test_idle_gap():
    jobs = [{"id": 1, "name": "A", "arrival": 3, "burst": 2, "priority": 1, "memory": 10}]
    r = build_result(Engine(jobs, "FCFS").run_all())
    assert r["metrics"]["idle_time"] == 3


def test_memory_wait():
    jobs = [{"id": 1, "name": "A", "arrival": 0, "burst": 2, "priority": 1, "memory": 800},
            {"id": 2, "name": "B", "arrival": 0, "burst": 2, "priority": 1, "memory": 800}]
    r = build_result(Engine(jobs, "RR", 1).run_all())
    assert any(e["type"] == "WAIT" for e in r["events"])
    assert all(j["status"] == "FINISHED" for j in r["jobs"])


def test_restore_gives_same_result():
    full = build_result(Engine(JOBS, "RR", 2).run_all())
    e = Engine(JOBS, "RR", 2)
    for _ in range(4):
        e.tick()
    rows = [{**j} for j in e.jobs.values()]
    e2 = Engine.restore(rows, "RR", 2, e.state())
    e2.run_all()
    assert {j["id"]: j["finish_time"] for j in e2.jobs.values()} == \
           {j["id"]: j["finish_time"] for j in build_result(Engine(JOBS, "RR", 2).run_all())["jobs"]}
    assert e2.memory_used == 0


def test_deadlock():
    procs = [{"id": "P1", "holds": ["R1"], "waits": ["R2"]},
             {"id": "P2", "holds": ["R2"], "waits": ["R1"]}]
    assert deadlock.detect(procs)["cycle"]
    assert deadlock.recover(procs)["steps"]
    assert not deadlock.detect(deadlock.recover(procs)["remaining"])["cycle"]


def test_deadlock_edges_from_job_resources():
    procs = [{"id": "A", "holds": ["R1"], "waits": ["R2"]},
             {"id": "B", "holds": ["R2"], "waits": ["R3"]},
             {"id": "C", "holds": ["R3"], "waits": ["R1"]},
             {"id": "D", "holds": ["R4"], "waits": []}]
    res = deadlock.detect(procs)
    assert {(e["from"], e["to"], e["resource"]) for e in res["edges"]} == \
        {("A", "B", "R2"), ("B", "C", "R3"), ("C", "A", "R1")}
    assert set(res["cycle"]) == {"A", "B", "C"}
    rec = deadlock.recover(procs)
    assert len(rec["steps"]) == 1 and not deadlock.detect(rec["remaining"])["cycle"]

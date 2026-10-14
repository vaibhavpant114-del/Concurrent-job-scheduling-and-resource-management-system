from __future__ import annotations

from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

class JobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    arrival_time: int = Field(default=0, ge=0)
    cpu_burst: int = Field(gt=0, le=1000)
    priority: int = Field(default=1, ge=0, le=100)
    memory_mb: int = Field(default=128, ge=1, le=65536)
    holds: list[str] = []
    requests: list[str] = []

class SimulationRequest(BaseModel):
    algorithm: Literal["FCFS", "SJF", "Priority", "Round Robin"] = "FCFS"
    quantum: int = Field(default=2, ge=1, le=100)
    total_memory_mb: int = Field(default=1024, ge=1, le=1048576)
    jobs: list[JobCreate] = Field(min_length=1, max_length=100)

class RecoveryRequest(BaseModel):
    job_id: str
    action: Literal["cancel", "rollback"] = "cancel"

app = FastAPI(title="Concurrent Job Scheduling and Resource Management System",
              version="2.0.0",
              description="Phase II educational OS scheduling/resource simulation.")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Phase II intentionally keeps each simulation in process memory. Persistent
# execution history and crash recovery are listed as Phase III work in the report.
latest_result: dict = {}

@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"status": "ok", "project": app.title, "phase": "II"}

@app.post("/api/simulate")
def simulate(payload: SimulationRequest):
    global latest_result
    jobs = []
    seen = set()
    for i, item in enumerate(payload.jobs, 1):
        name = item.name.strip()
        if not name:
            raise HTTPException(422, "Job names cannot be blank.")
        if name.lower() in seen:
            raise HTTPException(422, f"Duplicate job name: {name}")
        seen.add(name.lower())
        jobs.append({
            "id": f"J{i}", "name": name, "arrival_time": item.arrival_time,
            "cpu_burst": item.cpu_burst, "remaining": item.cpu_burst,
            "priority": item.priority, "memory_mb": item.memory_mb,
            "holds": sorted(set(x.strip() for x in item.holds if x.strip())),
            "requests": sorted(set(x.strip() for x in item.requests if x.strip())),
            "status": "New", "start_time": None, "completion_time": None,
            "turnaround_time": None, "waiting_time": None, "allocated": False,
            "recovery": None
        })
    if sum(j["memory_mb"] for j in jobs) < 0:
        raise HTTPException(422, "Invalid memory requirements.")

    total_memory = payload.total_memory_mb
    # The resource manager reserves each job's requested memory while it runs.
    # A job whose memory requirement exceeds total capacity can never execute.
    impossible = [j["name"] for j in jobs if j["memory_mb"] > total_memory]
    if impossible:
        raise HTTPException(422, "Memory requirement exceeds total capacity for: " + ", ".join(impossible))

    resource_owner = {}
    events = []
    timeline = []
    time = 0
    completed = set()
    cancelled = set()
    running_ids = set()
    allocated_memory = 0
    cpu_busy = 0
    context_switches = 0
    last_job = None
    deadlock_graph = {}
    deadlock_cycles = []

    by_id = {j["id"]: j for j in jobs}
    # Resource ownership is initialized from explicitly declared held resources,
    # enabling students to construct resource dependency scenarios.
    for j in jobs:
        for resource in j["holds"]:
            if resource not in resource_owner:
                resource_owner[resource] = j["id"]
            elif resource_owner[resource] != j["id"]:
                # First holder owns the exclusive resource; the later job will wait.
                pass

    def dependencies():
        graph = {j["id"]: set() for j in jobs if j["id"] not in completed and j["id"] not in cancelled}
        for j in jobs:
            if j["id"] not in graph:
                continue
            for r in j["requests"]:
                owner = resource_owner.get(r)
                if owner and owner != j["id"] and owner in graph:
                    graph[j["id"]].add(owner)
        return graph

    def find_cycles(graph):
        cycles, visiting, visited = [], [], set()
        def dfs(node):
            if node in visiting:
                cyc = visiting[visiting.index(node):] + [node]
                if cyc not in cycles:
                    cycles.append(cyc)
                return
            if node in visited:
                return
            visiting.append(node)
            for nxt in graph.get(node, ()):
                dfs(nxt)
            visiting.pop()
            visited.add(node)
        for node in graph:
            dfs(node)
        return cycles

    # Resource dependencies are checked before scheduling. A cycle is a simulated
    # deadlock; jobs remain visible until the user chooses recovery.
    deadlock_graph = dependencies()
    deadlock_cycles = find_cycles(deadlock_graph)
    deadlocked_ids = set(x for cycle in deadlock_cycles for x in cycle[:-1])

    for j in jobs:
        if j["id"] in deadlocked_ids:
            j["status"] = "Deadlocked"
        elif j["requests"] and any(resource_owner.get(r) not in (None, j["id"]) for r in j["requests"]):
            j["status"] = "Waiting for resource"
        else:
            j["status"] = "Ready"

    # Simulate scheduling only for jobs whose resource requests are currently available.
    # Jobs with resource dependencies stay waiting; recovery can release their resources.
    eligible = [j for j in jobs if j["status"] == "Ready"]
    ready_by_arrival = sorted(eligible, key=lambda j: (j["arrival_time"], j["id"]))
    rr_queue = deque()
    remaining = {j["id"]: j["cpu_burst"] for j in eligible}
    current_time = 0
    max_steps = sum(j["cpu_burst"] for j in eligible) + len(eligible) * 5 + 100
    steps = 0

    def choose_ready(queue, now):
        available = [j for j in queue if j["arrival_time"] <= now and remaining.get(j["id"], 0) > 0]
        if not available:
            return None
        if payload.algorithm == "SJF":
            return min(available, key=lambda j: (j["cpu_burst"], j["arrival_time"], j["id"]))
        if payload.algorithm == "Priority":
            return min(available, key=lambda j: (j["priority"], j["arrival_time"], j["id"]))
        return min(available, key=lambda j: (j["arrival_time"], j["id"]))

    pending = list(ready_by_arrival)
    while pending and steps < max_steps:
        steps += 1
        arrived = [j for j in pending if j["arrival_time"] <= current_time]
        if not arrived:
            next_arrival = min(j["arrival_time"] for j in pending)
            if next_arrival > current_time:
                timeline.append({"job_id": None, "job_name": "Idle", "start": current_time, "end": next_arrival, "kind": "idle"})
                current_time = next_arrival
            continue
        if payload.algorithm == "Round Robin":
            # Keep a queue of arrived jobs and append newly arrived jobs as time advances.
            for j in sorted([x for x in pending if x["arrival_time"] <= current_time and x["id"] not in [q["id"] for q in rr_queue]], key=lambda x: (x["arrival_time"], x["id"])):
                rr_queue.append(j)
            j = rr_queue.popleft() if rr_queue else arrived[0]
            duration = min(payload.quantum, remaining[j["id"]])
        else:
            j = choose_ready(pending, current_time)
            duration = remaining[j["id"]]
        if j is None:
            current_time += 1
            continue
        if j["memory_mb"] + allocated_memory > total_memory:
            j["status"] = "Waiting for memory"
            pending.remove(j)
            continue
        if j["start_time"] is None:
            j["start_time"] = current_time
        if last_job is not None and last_job != j["id"]:
            context_switches += 1
        last_job = j["id"]
        j["status"] = "Running"
        allocated_memory += j["memory_mb"]
        j["allocated"] = True
        events.append({"time": current_time, "type": "allocate", "job_id": j["id"], "memory_mb": j["memory_mb"]})
        start = current_time
        end = current_time + duration
        timeline.append({"job_id": j["id"], "job_name": j["name"], "start": start, "end": end, "kind": "run"})
        cpu_busy += duration
        current_time = end
        remaining[j["id"]] -= duration
        allocated_memory -= j["memory_mb"]
        j["allocated"] = False
        events.append({"time": current_time, "type": "release", "job_id": j["id"], "memory_mb": j["memory_mb"]})
        if remaining[j["id"]] == 0:
            j["status"] = "Completed"
            j["completion_time"] = current_time
            j["turnaround_time"] = current_time - j["arrival_time"]
            j["waiting_time"] = max(0, j["turnaround_time"] - j["cpu_burst"])
            completed.add(j["id"])
            # A completed job releases any exclusive resources it held.
            for resource, owner in list(resource_owner.items()):
                if owner == j["id"]:
                    del resource_owner[resource]
                    events.append({"time": current_time, "type": "resource_release", "job_id": j["id"], "resource": resource})
            pending = [x for x in pending if x["id"] != j["id"]]
        else:
            j["status"] = "Ready"
            if payload.algorithm == "Round Robin":
                # Add jobs that arrived during this quantum before re-queueing this job.
                for new_job in sorted([x for x in pending if x["arrival_time"] <= current_time and x["id"] != j["id"] and x["id"] not in [q["id"] for q in rr_queue]], key=lambda x: (x["arrival_time"], x["id"])):
                    rr_queue.append(new_job)
                rr_queue.append(j)
            else:
                # Preemptive continuation is only used for RR; other policies run to completion.
                pass
        if payload.algorithm != "Round Robin" and remaining[j["id"]] > 0:
            # Non-RR jobs run their full remaining burst in one segment.
            continue

    for j in jobs:
        if j["status"] == "Ready":
            j["status"] = "Waiting for memory" if j["memory_mb"] > total_memory else "Waiting"
    makespan = max((s["end"] for s in timeline), default=0)
    cpu_utilization = round((cpu_busy / makespan) * 100, 1) if makespan else 0
    latest_result = {
        "algorithm": payload.algorithm, "quantum": payload.quantum,
        "total_memory_mb": total_memory, "jobs": jobs, "timeline": timeline,
        "events": events, "resource_owner": resource_owner,
        "wait_for_graph": {k: sorted(v) for k, v in deadlock_graph.items()},
        "deadlock_cycles": deadlock_cycles,
        "metrics": {
            "cpu_utilization_percent": cpu_utilization,
            "memory_allocated_mb": 0,
            "memory_remaining_mb": total_memory,
            "cpu_busy_units": cpu_busy,
            "elapsed_time": makespan,
            "context_switches": context_switches,
            "completed_jobs": len(completed),
            "waiting_jobs": sum(1 for j in jobs if j["status"].startswith("Waiting")),
            "deadlocked_jobs": len(deadlocked_ids)
        }
    }
    return latest_result

@app.post("/api/recover")
def recover(payload: RecoveryRequest):
    global latest_result
    if not latest_result:
        raise HTTPException(400, "Run a simulation first.")
    job = next((j for j in latest_result["jobs"] if j["id"] == payload.job_id), None)
    if not job:
        raise HTTPException(404, "Job not found in the latest simulation.")
    if job["status"] not in ("Deadlocked", "Waiting for resource", "Waiting", "Waiting for memory"):
        raise HTTPException(400, "Recovery is available only for a waiting/deadlocked job.")
    job["status"] = "Cancelled" if payload.action == "cancel" else "Rolled back"
    job["recovery"] = payload.action
    # Release every resource held by the selected job.
    for resource, owner in list(latest_result.get("resource_owner", {}).items()):
        if owner == job["id"]:
            del latest_result["resource_owner"][resource]
    latest_result["events"].append({"type": "recovery", "job_id": job["id"], "action": payload.action})
    # Recompute the wait-for graph after release.
    active = {j["id"] for j in latest_result["jobs"] if j["status"] not in ("Completed", "Cancelled", "Rolled back")}
    graph = {j_id: set() for j_id in active}
    for j in latest_result["jobs"]:
        if j["id"] not in active:
            continue
        for resource in j["requests"]:
            owner = latest_result["resource_owner"].get(resource)
            if owner and owner != j["id"] and owner in active:
                graph[j["id"]].add(owner)
    latest_result["wait_for_graph"] = {k: sorted(v) for k, v in graph.items()}
    latest_result["deadlock_cycles"] = []
    latest_result["metrics"]["deadlocked_jobs"] = 0
    latest_result["metrics"]["waiting_jobs"] = sum(1 for j in latest_result["jobs"] if j["status"].startswith("Waiting"))
    return latest_result

@app.get("/api/result")
def result():
    if not latest_result:
        return {"message": "No simulation has been run yet."}
    return latest_result

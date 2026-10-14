import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["phase"] == "II"

def test_simulate_one_job():
    response = client.post("/api/simulate", json={
        "algorithm": "FCFS", "quantum": 2, "total_memory_mb": 512,
        "jobs": [{"name": "A", "arrival_time": 0, "cpu_burst": 3,
                  "priority": 1, "memory_mb": 128, "holds": [], "requests": []}]
    })
    assert response.status_code == 200
    body = response.json()
    assert body["jobs"][0]["status"] == "Completed"
    assert body["metrics"]["completed_jobs"] == 1

def test_detects_wait_for_cycle():
    response = client.post("/api/simulate", json={
        "algorithm": "FCFS", "quantum": 2, "total_memory_mb": 512,
        "jobs": [
            {"name": "A", "arrival_time": 0, "cpu_burst": 3, "priority": 1,
             "memory_mb": 128, "holds": ["Printer"], "requests": ["Scanner"]},
            {"name": "B", "arrival_time": 0, "cpu_burst": 2, "priority": 1,
             "memory_mb": 128, "holds": ["Scanner"], "requests": ["Printer"]}
        ]
    })
    assert response.status_code == 200
    assert response.json()["deadlock_cycles"]

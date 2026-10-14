# Concurrent Job Scheduling and Resource Management System
**Team:** Home Squad · **Course/Project ID:** OSDBMS-V-2026-T253  
**Phase:** II — simulated CPU/memory monitoring, resource availability, deadlock detection and recovery.

## Features
- Job input: arrival time, CPU burst, priority, memory requirement, held resources and requested resources.
- Scheduling policies: FCFS, SJF, Priority (smaller number means higher priority), and Round Robin.
- Simulated CPU utilization, job completion/waiting metrics, memory capacity and resource allocation/release events.
- Wait-for graph and cycle-based deadlock detection.
- Recovery action for waiting/deadlocked jobs: cancel or roll back, releasing resources held by that job.
- FastAPI JSON API and browser-based dashboard.
- This Phase II build keeps the latest simulation in process memory. PostgreSQL-backed persistent history, crash recovery and replay, and interactive step-by-step Gantt controls remain Phase III work, as specified in the report.

## Requirements
- Python 3.10 or newer
- macOS, Windows, or Linux
- Internet is needed only to install Python packages (unless already cached).
- PostgreSQL is **not required to run this Phase II demo**. The report identifies PostgreSQL persistence as planned/Phase III work.

## Run on macOS
1. Unzip the project.
2. Open Terminal and enter the project directory, for example:
   ```bash
   cd ~/Downloads/concurrent_job_scheduling_system
   ```
3. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```
4. Activate it:
   ```bash
   source .venv/bin/activate
   ```
5. Install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```
6. Start the server:
   ```bash
   python3 -m uvicorn main:app --reload
   ```
7. Open **http://127.0.0.1:8000** in your browser.
8. API documentation is at **http://127.0.0.1:8000/docs**.

## Run on Windows
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```
If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

## Try the demo
The page starts with three example jobs. Click **Run simulation** and inspect the schedule, resource metrics, timeline, wait-for graph and deadlock status.

To demonstrate deadlock, create two jobs with:
- Job A holds `Printer` and requests `Scanner`
- Job B holds `Scanner` and requests `Printer`

Use the exact same spelling for resource names. Run the simulation. The wait-for graph should show a cycle. Use **Cancel** or **Roll back** on one of the waiting/deadlocked jobs to demonstrate resource release.

## API endpoints
- `GET /api/health` — server status
- `POST /api/simulate` — validate jobs and run selected scheduling simulation
- `GET /api/result` — latest in-memory result
- `POST /api/recover` — cancel/roll back a waiting or deadlocked job
- `GET /docs` — interactive Swagger API documentation

## Project structure
```text
concurrent_job_scheduling_system/
├── main.py
├── requirements.txt
├── README.md
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── tests/
    └── test_api.py
```

## Notes for the project viva
- This is a **simulation**, not a monitor of real computer CPU or RAM.
- CPU utilization is computed from simulated busy time / simulated elapsed time.
- Smaller priority values represent higher priority.
- The deadlock demonstration is intentionally controllable: jobs declare exclusive resources they hold and request so a wait-for cycle can be constructed.
- The current build is a Phase II implementation scaffold; do not claim PostgreSQL persistence, crash restoration, or an interactive playback Gantt chart is complete.

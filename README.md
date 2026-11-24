# Concurrent Job Scheduling and Resource Management System
Team Home Squad (T253) - OSDBMS-V-2026-T253

Teaching tool: FCFS, SJF, Priority and Round Robin scheduling, simulated CPU/memory monitor,
deadlock detection/recovery (wait-for graph), saved history with crash recovery, and an
interactive Gantt chart with step/auto playback and four-rule comparison.
CPU and memory values are simulated; the real computer is never measured or controlled.

## Run in VS Code (Windows)
1. Install Python 3.10+ (tick "Add Python to PATH") and VS Code with the Python extension.
2. File > Open Folder... > choose this folder.
3. Terminal > New Terminal, then:
       python -m venv .venv
       .venv\Scripts\activate
       pip install -r requirements.txt
   (macOS/Linux: `python3 -m venv .venv` and `source .venv/bin/activate`)
4. Start the server:
       uvicorn backend.main:app --reload
5. Open http://127.0.0.1:8000 (API docs: http://127.0.0.1:8000/docs).

By default data is saved in a local SQLite file (jobsched.db). To use PostgreSQL:
create a database (`CREATE DATABASE jobsched;`), copy `.env.example` to `.env`, and set
`DATABASE_URL=postgresql+psycopg2://postgres:PASSWORD@localhost:5432/jobsched`.
Tables are created automatically (see database/schema.sql).

## Deadlock demo
Each job has **Holds** and **Waits for** columns (e.g. Holds `R1`, Waits for `R2`). If job A waits
for a resource job B holds, the wait-for graph draws A -> B. Click **Load deadlock example**, then
**Detect deadlock** to see the loop in red, and **Recover** to stop a victim job. Simulations are
refused while a deadlock exists among the jobs.

## Tests
    python -m pytest -q tests

## Folders
- backend/engine.py    scheduler, simulated memory, step-by-step engine, save/restore state
- backend/deadlock.py  wait-for graph, loop detection, recovery
- backend/storage.py   database tables, one-transaction saves, history, recovery queries
- backend/main.py      FastAPI routes
- frontend/            dashboard, Gantt chart, playback, history, live run, deadlock panel

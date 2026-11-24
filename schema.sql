-- Reference schema (the app creates these tables automatically on start-up).
CREATE TABLE jobs (id SERIAL PRIMARY KEY, name VARCHAR(60) NOT NULL, arrival INT NOT NULL,
  burst INT NOT NULL, priority INT NOT NULL, memory INT NOT NULL);
CREATE TABLE runs (id SERIAL PRIMARY KEY, algorithm VARCHAR(10) NOT NULL, quantum INT NOT NULL,
  status VARCHAR(12) NOT NULL, sim_time INT NOT NULL DEFAULT 0, state_json TEXT NOT NULL DEFAULT '{}',
  created_at TIMESTAMP NOT NULL);
CREATE TABLE run_jobs (run_id INT REFERENCES runs(id) ON DELETE CASCADE, job_id INT NOT NULL,
  name VARCHAR(60), arrival INT, burst INT, priority INT, memory INT, remaining INT,
  status VARCHAR(12), start_time INT, finish_time INT, PRIMARY KEY (run_id, job_id));
CREATE TABLE run_events (id SERIAL PRIMARY KEY, run_id INT REFERENCES runs(id) ON DELETE CASCADE,
  seq INT NOT NULL, time INT NOT NULL, type VARCHAR(12) NOT NULL, job_id INT, detail TEXT);
CREATE TABLE status_changes (id SERIAL PRIMARY KEY, run_id INT REFERENCES runs(id) ON DELETE CASCADE,
  job_id INT, time INT, old_status VARCHAR(12), new_status VARCHAR(12));
CREATE TABLE resource_events (id SERIAL PRIMARY KEY, run_id INT REFERENCES runs(id) ON DELETE CASCADE,
  job_id INT, time INT, action VARCHAR(12), memory_used INT, memory_free INT);

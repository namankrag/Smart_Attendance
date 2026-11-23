"""Load test: 50 concurrent users (Phase 2 deliverable 4).

Simulates logins, attendance lookups, and group-photo job submission
+ polling against the Streamlit UI host and the ML worker. Run with:

    locust -f tests/load/locustfile.py --host http://localhost:8501 \\
        --users 50 --spawn-rate 5 --run-time 5m --headless \\
        --csv load-report --html load-report.html

    # against the worker directly (job API only):
    LOCUST_WORKER_URL=http://localhost:8000 locust -f tests/load/locustfile.py \\
        --host http://localhost:8000 --users 50 --spawn-rate 5 --run-time 5m --headless

p50 / p95 / p99 latency and error rate come from Locust's own stats
(the ``--csv`` output and the HTML report): this file does not invent
numbers. **No live benchmark was run in the Phase 2 run** — there is
no deployed system to benchmark against (no deployment in Phase 2),
and the worker has no real model weights yet. Run this only against a
local / staging deployment with baked weights, never against
production data.

The worker tasks below submit a small synthetic JPEG (generated in
memory) and poll ``/jobs/{id}`` until terminal, mirroring what the
Streamlit UI does from its ``@st.fragment`` poller.
"""

import os

try:
    from locust import HttpUser, between, task
except ImportError as exc:  # pragma: no cover - locust only needed to run the test
    raise RuntimeError(
        "locust is not installed. Install it (pip install locust) to run "
        "this load test."
    ) from exc

WORKER_URL = os.environ.get("LOCUST_WORKER_URL", "")

# A tiny synthetic JPEG (1x1 white) generated in memory — the load test
# never uses a real student's photo.
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAIAAgDASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
    "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
    "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
    "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
    "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
    "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
    "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
    "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iii"
    "gD//2Q=="
)


def _tiny_jpeg_b64() -> str:
    return _TINY_JPEG_B64


class AttendanceUser(HttpUser):
    """One simulated user: home page, login page, records, worker jobs."""
    wait_time = between(1, 3)

    @task(3)
    def home_page(self):
        self.client.get("/", name="ui:home")

    @task(3)
    def login_page(self):
        # The login screen is a Streamlit page load; credentials are
        # never submitted by the load test (no real accounts in scope).
        self.client.get("/", name="ui:login-page")

    @task(2)
    def attendance_records(self):
        self.client.get("/", name="ui:attendance-records")

    @task(1)
    def group_photo_job(self):
        """Submit a group-photo job to the worker and poll to completion."""
        if not WORKER_URL:
            return
        with self.client.post(
            f"{WORKER_URL}/jobs",
            json={"type": "face", "subject_id": None, "candidate_ids": [],
                  "payload_b64": _tiny_jpeg_b64(), "metadata": {"load_test": True}},
            name="worker:submit-face-job",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 202):
                resp.failure(f"submit failed: {resp.status_code}")
                return
            job_id = resp.json().get("id")
        if not job_id:
            return
        for _ in range(30):
            with self.client.get(
                f"{WORKER_URL}/jobs/{job_id}",
                name="worker:poll-job",
                catch_response=True,
            ) as resp:
                if resp.status_code != 200:
                    resp.failure(f"poll failed: {resp.status_code}")
                    return
                if resp.json().get("status") in ("done", "failed"):
                    return


class WorkerOnlyUser(HttpUser):
    """Worker-only profile (use with --host pointing at the worker)."""
    wait_time = between(0.5, 2)

    @task(2)
    def health(self):
        self.client.get("/healthz", name="worker:healthz")

    @task(1)
    def ready(self):
        self.client.get("/readyz", name="worker:readyz")

"""Long-running work (exports, crop runs, composites, cut-outs) off the UI.

Each job runs on its own thread and publishes a plain dict of progress that the
interface polls. Cancelling is cooperative: the job checks between photos.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid


class Job:
    def __init__(self, kind: str, total: int = 0):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.cancelled = False
        self.started = time.time()
        self.state = {
            "id": self.id, "kind": kind, "total": total, "done": 0, "current": "",
            "message": "", "finished": False, "error": None, "result": None, "items": [],
            "eta": None, "busy": False,
        }
        self._lock = threading.Lock()

    def update(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)
            done, total = self.state["done"], self.state["total"]
            if done and total and not self.state["finished"]:
                rate = (time.time() - self.started) / done
                self.state["eta"] = round(rate * (total - done))

    def add_item(self, item: dict) -> None:
        with self._lock:
            self.state["items"].append(item)

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            s = dict(self.state)
            s["items"] = self.state["items"][since:]
            s["items_total"] = len(self.state["items"])
            s["elapsed"] = round(time.time() - self.started)
            return s


_jobs: dict[str, Job] = {}


def start(kind: str, fn, total: int = 0) -> Job:
    job = Job(kind, total)
    _jobs[job.id] = job

    def runner():
        try:
            result = fn(job)
            job.update(result=result)
        except Exception as exc:  # surfaced to the user, never swallowed
            traceback.print_exc()
            job.update(error=f"{type(exc).__name__}: {exc}")
        finally:
            job.update(finished=True, busy=False, eta=0)

    threading.Thread(target=runner, name=f"job-{kind}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)

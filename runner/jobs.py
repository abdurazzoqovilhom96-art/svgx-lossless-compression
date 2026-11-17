"""Job ledger (SQLite, atomic commits), per-run lock, bounded parallel dispatch with retry, resume,
defect pause and an authorization check before every launch.

Idempotent job key: split | input_sha256 | build_id | method | repeat | task.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .common import utc_now


class TransientError(RuntimeError):
    """Retryable failure (timeouts, resource exhaustion, I/O hiccups)."""


class DefectError(RuntimeError):
    """Deterministic correctness defect (e.g. round-trip mismatch of a project stream)."""


@dataclass
class JobSpec:
    split: str
    input_sha256: str
    build_id: str
    method: str
    repeat: int
    task: str
    payload: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return "|".join([self.split, self.input_sha256, self.build_id, self.method, str(self.repeat), self.task])


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  key TEXT PRIMARY KEY, split TEXT, input_sha256 TEXT, build_id TEXT, method TEXT, repeat INTEGER,
  task TEXT, payload TEXT, status TEXT, attempts INTEGER DEFAULT 0, result TEXT, error TEXT, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, attempt INTEGER, started_utc TEXT, finished_utc TEXT,
  status TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS pauses(scope TEXT PRIMARY KEY, reason TEXT, utc TEXT, evidence TEXT);
"""


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def _tx(self, fn):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                r = fn(self.db)
                self.db.execute("COMMIT")
                return r
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def register(self, jobs: list[JobSpec]) -> None:
        def f(db):
            for j in jobs:
                db.execute("INSERT OR IGNORE INTO jobs(key,split,input_sha256,build_id,method,repeat,task,payload,"
                           "status,updated_utc) VALUES(?,?,?,?,?,?,?,?,'pending',?)",
                           (j.key, j.split, j.input_sha256, j.build_id, j.method, j.repeat, j.task,
                            json.dumps(j.payload, sort_keys=True), utc_now()))
        self._tx(f)

    def status(self, key: str) -> str | None:
        with self._lock:
            row = self.db.execute("SELECT status FROM jobs WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_status(self, key: str, status: str, result=None, error: str | None = None) -> None:
        self._tx(lambda db: db.execute("UPDATE jobs SET status=?, result=?, error=?, updated_utc=? WHERE key=?",
                                       (status, json.dumps(result, sort_keys=True) if result is not None else None,
                                        error, utc_now(), key)))

    def begin_attempt(self, key: str) -> int:
        def f(db):
            db.execute("UPDATE jobs SET attempts=attempts+1, status='running', updated_utc=? WHERE key=?", (utc_now(), key))
            n = db.execute("SELECT attempts FROM jobs WHERE key=?", (key,)).fetchone()[0]
            db.execute("INSERT INTO attempts(key,attempt,started_utc,status) VALUES(?,?,?,'running')", (key, n, utc_now()))
            return n
        return self._tx(f)

    def end_attempt(self, key: str, attempt: int, status: str, error: str | None = None) -> None:
        self._tx(lambda db: db.execute("UPDATE attempts SET finished_utc=?, status=?, error=? WHERE key=? AND attempt=?",
                                       (utc_now(), status, error, key, attempt)))

    def event(self, kind: str, detail) -> None:
        self._tx(lambda db: db.execute("INSERT INTO events(utc,kind,detail) VALUES(?,?,?)",
                                       (utc_now(), kind, json.dumps(detail, sort_keys=True))))

    def pause(self, scope: str, reason: str, evidence) -> None:
        self._tx(lambda db: db.execute("INSERT OR REPLACE INTO pauses(scope,reason,utc,evidence) VALUES(?,?,?,?)",
                                       (scope, reason, utc_now(), json.dumps(evidence, sort_keys=True))))

    def paused_scopes(self) -> dict:
        with self._lock:
            return {r[0]: r[1] for r in self.db.execute("SELECT scope, reason FROM pauses")}

    def rows(self, where: str = "1=1", args: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self.db.execute(f"SELECT key,split,input_sha256,build_id,method,repeat,task,payload,status,attempts,"
                                  f"result,error FROM jobs WHERE {where} ORDER BY key", args)
            cols = [c[0] for c in cur.description]
            out = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
                d["result"] = json.loads(d["result"]) if d["result"] else None
                out.append(d)
            return out

    def attempts(self) -> list[dict]:
        with self._lock:
            cur = self.db.execute("SELECT key,attempt,started_utc,finished_utc,status,error FROM attempts ORDER BY id")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def events(self) -> list[dict]:
        with self._lock:
            cur = self.db.execute("SELECT utc,kind,detail FROM events ORDER BY id")
            return [{"utc": u, "kind": k, "detail": json.loads(d)} for u, k, d in cur.fetchall()]


class RunLock:
    """Exclusive per-run lock file; a stale lock (dead PID) is taken over and recorded."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.held = False

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            import psutil  # noqa: PLC0415
            return psutil.pid_exists(pid)
        except ImportError:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def acquire(self) -> str | None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stale = None
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(json.dumps({"pid": os.getpid(), "utc": utc_now()}))
                self.held = True
                return stale
            except FileExistsError:
                try:
                    info = json.loads(self.path.read_text())
                except (OSError, ValueError):
                    info = {"pid": -1}
                if info.get("pid") != os.getpid() and self._alive(int(info.get("pid", -1))):
                    raise RuntimeError(f"bu run boshqa jarayon tomonidan band (pid {info.get('pid')})")
                stale = info
                self.path.unlink(missing_ok=True)
        raise RuntimeError("run lock olinmadi")

    def release(self) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


Gate = Callable[[JobSpec], tuple[bool, str]]
Worker = Callable[[JobSpec], dict]


def pause_scope(job: JobSpec) -> str:
    return f"{job.build_id}|{job.method}"


def dispatch(ledger: Ledger, jobs: list[JobSpec], worker: Worker, gate: Gate, *, max_workers: int = 1,
             retries: int = 2, on_progress: Callable[[int, int], None] | None = None) -> dict:
    """Run every not-yet-done job. Returns counters. The gate is consulted before each launch."""
    ledger.register(jobs)
    todo = []
    for j in jobs:
        st = ledger.status(j.key)
        if st == "done":
            continue
        todo.append(j)
    counters = {"launched": 0, "done": 0, "failed": 0, "blocked": 0, "paused": 0, "skipped_done": len(jobs) - len(todo)}
    lock = threading.Lock()

    def attempt(j: JobSpec) -> None:
        paused = ledger.paused_scopes()
        if pause_scope(j) in paused or "ALL" in paused:
            ledger.set_status(j.key, "paused", error=paused.get(pause_scope(j), paused.get("ALL")))
            with lock:
                counters["paused"] += 1
            return
        ok, why = gate(j)
        if not ok:
            ledger.set_status(j.key, "blocked", error=why)
            with lock:
                counters["blocked"] += 1
            return
        for _ in range(retries + 1):
            n = ledger.begin_attempt(j.key)
            with lock:
                counters["launched"] += 1
            try:
                res = worker(j)
            except TransientError as exc:
                ledger.end_attempt(j.key, n, "transient", str(exc))
                ledger.set_status(j.key, "pending", error=str(exc))
                continue
            except DefectError as exc:
                ledger.end_attempt(j.key, n, "defect", str(exc))
                ledger.set_status(j.key, "defect", error=str(exc))
                ledger.pause(pause_scope(j), str(exc), {"key": j.key})
                ledger.event("defect_pause", {"scope": pause_scope(j), "key": j.key, "error": str(exc)})
                with lock:
                    counters["failed"] += 1
                return
            except Exception as exc:  # noqa: BLE001 - recorded as a failed attempt
                ledger.end_attempt(j.key, n, "error", repr(exc))
                ledger.set_status(j.key, "failed", error=repr(exc))
                with lock:
                    counters["failed"] += 1
                return
            ledger.end_attempt(j.key, n, "done")
            ledger.set_status(j.key, "done", result=res)
            with lock:
                counters["done"] += 1
            return
        ledger.set_status(j.key, "failed", error="retries exhausted")
        with lock:
            counters["failed"] += 1

    total = len(todo)
    finished = 0
    if max_workers <= 1:
        for j in todo:
            attempt(j)
            finished += 1
            if on_progress:
                on_progress(finished, total)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            pending = {ex.submit(attempt, j) for j in todo}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    fut.result()
                    finished += 1
                    if on_progress:
                        on_progress(finished, total)
    return counters

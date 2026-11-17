"""A04/A14 targeted check: re-decode the stored structured G streams of the confirmation split with the frozen
independent Python reference decoder and compare the restored bytes with the original SHA-256.

Scope is fixed BEFORE execution in ../TARGETED_JOB_PLAN.json (written by `plan`), then executed by `run`:
  python a05_targeted_redecode.py plan   -> writes the plan (no codec job)
  python a05_targeted_redecode.py run    -> executes exactly the planned jobs, logs ../TARGETED_JOBS.jsonl
Limits (user brief §2.3): <= 128 codec jobs, <= 48 distinct inputs, <= 30 min wall time; never extended automatically.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ROOT = A.parents[1]
RUN = ROOT / "results" / "20261114_050438_SVGX-2026-11-A"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
REF = ROOT / "reference" / "decode.py"
PLAN = A / "TARGETED_JOB_PLAN.json"
LOG = A / "TARGETED_JOBS.jsonl"
LIMITS = {"new_codec_jobs_max": 128, "distinct_new_test_inputs_max": 48, "additional_codec_wall_time_minutes_max": 30,
          "per_job_timeout_s": 120}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan() -> None:
    rows = [r for r in csv.DictReader(open(A / "derived" / "per_file_from_ledger.csv", encoding="utf-8"))
            if r["split"] == "confirmation" and r["branch_G"] == "structured"]
    con = sqlite3.connect(f"file:{RUN / 'ledger.sqlite'}?mode=ro&immutable=1", uri=True)
    jobs = []
    for r in sorted(rows, key=lambda r: r["file_id"]):
        res = json.loads(con.execute("select result from jobs where task='size' and method='svgx' and split='confirmation' "
                                     "and input_sha256=?", (r["sha256"],)).fetchone()[0])
        g = res["profiles"]["G"]
        stream = RUN / "03_raw" / "streams" / "confirmation" / r["sha256"][:16] / "svgx" / g["verify_final"]["stream"]
        jobs.append({"job": len(jobs) + 1, "file_id": r["file_id"], "input_sha256": r["sha256"], "stream": str(stream.relative_to(ROOT)),
                     "expected_stream_sha256": g["final_sha256"], "expected_stream_len": int(r["C_G"]),
                     "decoder": "reference/decode.py (frozen sha256 554defc7...)", "kind": "python_reference_decode"})
    p = {"created_utc": utc(), "purpose": "A04/A14: stored structured G streams of the confirmation split decode byte-exactly today "
                                          "with the frozen independent decoder (ledger claims vs stored artifacts)",
         "selection_rule": "census of all confirmation files whose final G stream is structured (branch_G == structured); "
                           "raw-branch G streams are byte-identical to the independent brotli.exe stream (checked by hash, no job)",
         "limits": LIMITS, "planned_codec_jobs": len(jobs), "distinct_inputs": len({j['input_sha256'] for j in jobs}),
         "expected_wall_time_minutes": 2, "outputs": "temporary directory, deleted after hashing", "jobs": jobs}
    assert p["planned_codec_jobs"] <= LIMITS["new_codec_jobs_max"] and p["distinct_inputs"] <= LIMITS["distinct_new_test_inputs_max"]
    PLAN.write_text(json.dumps(p, indent=1), encoding="utf-8")
    print(f"plan: {len(jobs)} jobs -> {PLAN}")


def run() -> None:
    p = json.loads(PLAN.read_text(encoding="utf-8"))
    done = set()
    if LOG.exists():
        done = {json.loads(l)["job"] for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()}
    t0 = time.monotonic()
    used = len(done)
    with tempfile.TemporaryDirectory() as td, open(LOG, "a", encoding="utf-8") as log:
        for j in p["jobs"]:
            if j["job"] in done:
                continue
            if used >= LIMITS["new_codec_jobs_max"] or (time.monotonic() - t0) > 60 * LIMITS["additional_codec_wall_time_minutes_max"]:
                log.write(json.dumps({"job": j["job"], "status": "NOT_RUN_LIMIT", "utc": utc()}) + "\n")
                continue
            s = ROOT / j["stream"]
            rec = {"job": j["job"], "file_id": j["file_id"], "started_utc": utc()}
            rec["stream_exists"] = s.exists()
            rec["stream_sha256_ok"] = s.exists() and sha(s) == j["expected_stream_sha256"]
            rec["stream_len_ok"] = s.exists() and s.stat().st_size == j["expected_stream_len"]
            outp = Path(td) / f"{j['job']}.svg"
            t = time.perf_counter()
            try:
                cp = subprocess.run([str(PY), "-I", str(REF), str(s), str(outp)], capture_output=True, timeout=LIMITS["per_job_timeout_s"])
                rec["returncode"] = cp.returncode
                rec["stderr"] = cp.stderr.decode("utf-8", "replace")[-300:]
            except subprocess.TimeoutExpired:
                rec["returncode"] = None
                rec["stderr"] = "timeout"
            used += 1
            rec["elapsed_s"] = round(time.perf_counter() - t, 3)
            rec["restored_sha256_ok"] = outp.exists() and sha(outp) == j["input_sha256"]
            rec["status"] = "OK" if (rec["stream_sha256_ok"] and rec["stream_len_ok"] and rec["returncode"] == 0
                                     and rec["restored_sha256_ok"]) else "FAIL"
            if outp.exists():
                outp.unlink()
            log.write(json.dumps(rec) + "\n")
            log.flush()
    lines = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(json.dumps({"jobs_logged": len(lines), "ok": sum(l["status"] == "OK" for l in lines),
                      "fail": sum(l["status"] == "FAIL" for l in lines),
                      "codec_jobs_used": sum(l["status"] in ("OK", "FAIL") for l in lines),
                      "wall_s": round(time.monotonic() - t0, 1)}, indent=1))


if __name__ == "__main__":
    {"plan": plan, "run": run}[sys.argv[1]]()

"""Run the approved REV1 experiments on the confirmation split in the frozen order R0 -> B1 -> B3 -> B2 -> analysis.

Each stage checks the approval itself (common.require_approval); a failing stage stops the run (protocol §6).
Stages already complete are resumed, not repeated (B1/B2/B3 keep per-file JSONL records).
Log: results_rev1/run_all.log
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
from common import OUT, PY, REV1, require_approval  # noqa: E402

STAGES = [("R0", ["rev1/r0_regression.py", "confirmation"]),
          ("B1", ["rev1/b1_geometry.py", "confirmation"]),
          ("B3", ["rev1/b3_timing.py", "confirmation"]),
          ("B2", ["rev1/b2_baselines.py", "confirmation"]),
          ("analysis", ["rev1/analysis.py", "confirmation"])]


def main() -> int:
    only = sys.argv[1:]
    log = OUT / "run_all.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    for stage, argv in STAGES:
        if only and stage not in only:
            continue
        require_approval(stage)
        t0 = dt.datetime.now(dt.timezone.utc)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n=== {stage} start {t0.isoformat()} ===\n")
        print(f"=== {stage} ===", flush=True)
        with open(log, "a", encoding="utf-8") as f:
            r = subprocess.run([str(PY), *argv], cwd=str(REV1), stdout=f, stderr=subprocess.STDOUT)
        t1 = dt.datetime.now(dt.timezone.utc)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"=== {stage} exit {r.returncode} at {t1.isoformat()} ({(t1 - t0).total_seconds():.0f} s) ===\n")
        print(f"    exit {r.returncode} ({(t1 - t0).total_seconds():.0f} s)", flush=True)
        if r.returncode != 0:
            print(f"[REV1] stage {stage} failed; the run stops here (see {log}).")
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

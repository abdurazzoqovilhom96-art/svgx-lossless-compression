"""A01: corrected completeness accounting. No codec jobs.

The frozen report builder (reporting/build.py lines 80-87) counts every method in EXTERNAL + SPEED_ONLY without a
size result as "missing". The frozen controller (runner/controller.py line 150) never schedules size jobs for
speed-only methods (zstd1, gzip1). This script classifies every expected (file, method, task) cell explicitly:
measured / not_scheduled_by_design / not_applicable / failed / missing, and writes original and corrected counts
side by side. The frozen files are not modified (they are hash-bound by state/freeze.json).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ROOT = A.parents[1]
RUN = ROOT / "results" / "20261114_050438_SVGX-2026-11-A"
SIZE_METHODS = ["svgx", "brotli11", "xwrt_l6", "xz9e", "ppmd7z", "zstd19", "gzip9"]   # scheduled by controller.size_jobs
SPEED_ONLY = ["zstd1", "gzip1"]                                                        # timing only (speed_only=True)


def classify(result: dict | None, scheduled: bool) -> str:
    if not scheduled:
        return "not_scheduled_by_design"
    if result is None:
        return "missing"
    if result.get("available") is False:
        return "not_applicable"
    if "roundtrip_ok" in result and not result["roundtrip_ok"]:
        return "failed"
    return "measured"


def main() -> dict:
    con = sqlite3.connect(f"file:{RUN / 'ledger.sqlite'}?mode=ro&immutable=1", uri=True)
    res = {}
    for split, sha, method, result in con.execute("select split, input_sha256, method, result from jobs where task='size' and status='done'"):
        res[(split, sha, method)] = json.loads(result)
    orig = json.loads((RUN / "11_reports" / "completeness_audit.json").read_text(encoding="utf-8"))
    out = {"original_report": {k: v for k, v in orig.items() if "missing" in k}, "corrected": {}}
    for split in ("pilot", "confirmation"):
        man = list(csv.DictReader(open(RUN / "02_corpus" / f"{split}.csv", encoding="utf-8")))
        c = Counter()
        for m in man:
            for meth in SIZE_METHODS:
                c[(meth, classify(res.get((split, m["sha256"], meth)), True))] += 1
            for meth in SPEED_ONLY:
                c[(meth, classify(res.get((split, m["sha256"], meth)), False))] += 1
        by_status = Counter()
        for (meth, st), n in c.items():
            by_status[st] += n
        paired_complete = sum(1 for m in man if all((split, m["sha256"], meth) in res for meth in SIZE_METHODS))
        out["corrected"][split] = {"files": len(man), "cells_by_status": dict(by_status),
                                   "cells_by_method_status": {f"{k[0]}|{k[1]}": v for k, v in sorted(c.items())},
                                   "files_with_complete_paired_size_set": paired_complete,
                                   "missing_measurements_corrected": by_status.get("missing", 0) + by_status.get("failed", 0)}
    (A / "derived" / "a07_completeness.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

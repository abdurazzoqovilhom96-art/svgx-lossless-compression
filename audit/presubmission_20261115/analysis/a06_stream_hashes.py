"""A14: every stored final stream (5 arms + raw.br + 7 size comparators) hashes to the value in the ledger. No codec jobs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ROOT = A.parents[1]
RUN = ROOT / "results" / "20261114_050438_SVGX-2026-11-A"
con = sqlite3.connect(f"file:{RUN / 'ledger.sqlite'}?mode=ro&immutable=1", uri=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


checked = ok = 0
bad = []
for split, s256, method, result in con.execute("select split, input_sha256, method, result from jobs where task='size'"):
    r = json.loads(result)
    if method == "svgx":
        base = RUN / "03_raw" / "streams" / split / s256[:16] / "svgx"
        items = [(base / pp["verify_final"]["stream"], pp["final_sha256"]) for pp in r["profiles"].values()]
    else:
        items = [(RUN / r["stream"], r["sha256"])]
    for p, h in items:
        checked += 1
        if p.exists() and sha(p) == h:
            ok += 1
        else:
            bad.append(str(p))
res = {"streams_checked": checked, "hash_equal_to_ledger": ok, "mismatch_or_missing": bad[:50], "mismatch_count": len(bad)}
(A / "derived" / "a06_stream_hashes.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1))

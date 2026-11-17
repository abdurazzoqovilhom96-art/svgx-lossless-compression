"""REV1 B3: fixed timing sample (written before freeze; docs/PROTOCOL_REV1.md §B3).

S: every confirmation file whose frozen G output is the structured branch (39 files).
R: for each S file in sha256 order, the unused confirmation file with a raw-branch G output whose size is closest
   on the log scale, |ln(size_R / size_S)|; ties broken by SHA-256("SVGX-REV1/timing/v1" + file sha256).
Uses only the frozen manifest and ledger (branch and size), never a timing result. Writes config/b3_sample.csv.
"""
from __future__ import annotations

import csv
import hashlib
import math
import sys

sys.stdout.reconfigure(encoding="utf-8")
from common import REV1, ledger_size_results, manifest  # noqa: E402

SEED = "SVGX-REV1/timing/v1"


def main() -> int:
    rows = manifest("confirmation")
    led = ledger_size_results({r["file_id"] for r in rows})
    for r in rows:
        r["branch"] = led[r["file_id"]]["profiles"]["G"]["invariants"]["branch"]
    S = sorted((r for r in rows if r["branch"] == "structured"), key=lambda r: r["sha256"])
    pool = [r for r in rows if r["branch"] == "raw"]
    used, out = set(), []
    for s in S:
        size_s = int(s["size"])
        best = min((r for r in pool if r["file_id"] not in used),
                   key=lambda r: (abs(math.log(int(r["size"]) / size_s)),
                                  hashlib.sha256((SEED + r["sha256"]).encode()).hexdigest()))
        used.add(best["file_id"])
        out.append(("S", s))
        out.append(("R", best))
    dst = REV1 / "config" / "b3_sample.csv"
    with open(dst, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "pair", "file_id", "sha256", "size", "family", "category", "branch"])
        for i, (g, r) in enumerate(out):
            w.writerow([g, i // 2, r["file_id"], r["sha256"], r["size"], r["family"], r["category"], r["branch"]])
    print(f"[B3-sample] S {len(S)} structured, R {len(used)} raw -> {dst}")
    return 0 if len(S) == 39 and len(used) == 39 else 1


if __name__ == "__main__":
    sys.exit(main())

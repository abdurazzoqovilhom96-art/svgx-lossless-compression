"""Record the user's decision on the REV1 experiments (run ONLY after the user has answered in the conversation).

usage: python rev1/approve.py approve|decline --scope R0,B1,B3,B2,analysis --note "verbatim user answer"
The record is bound to the SHA-256 of state/freeze_rev1.json; every experiment script checks it before running.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

sys.stdout.reconfigure(encoding="utf-8")
from common import APPROVAL, FREEZE, sha256_file, write_json  # noqa: E402

STAGES = {"R0", "B1", "B2", "B3", "analysis"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("decision", choices=["approve", "decline"])
    ap.add_argument("--scope", required=True)
    ap.add_argument("--note", required=True)
    a = ap.parse_args()
    if not FREEZE.exists():
        print("[approve] no freeze record; freeze first")
        return 1
    scope = [s.strip() for s in a.scope.split(",") if s.strip()]
    bad = [s for s in scope if s not in STAGES]
    if bad:
        print("[approve] unknown stages:", bad)
        return 1
    rec = {"decision": a.decision, "scope": scope, "note": a.note, "freeze_sha256": sha256_file(FREEZE),
           "recorded_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}
    write_json(APPROVAL, rec)
    print(f"[approve] {a.decision} {scope} bound to freeze {rec['freeze_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())

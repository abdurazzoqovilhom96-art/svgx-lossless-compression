"""REV1 regression gate R0 (docs/PROTOCOL_REV1.md §R0).

The REV1 build, run with its DEFAULT settings, must reproduce the frozen run byte for byte:
  * fixtures: every stream of `encode-all` equals the frozen binary's output and fixtures/synthetic/expected.json;
  * corpus split: for every file, raw.br == ledger baseline_sha256, and for each profile D/P/I/U/G the final and the
    forced stream SHA-256 equal the ledger's final_sha256 / forced_sha256 (absence must match), and stats.json equals
    the ledger's stats object exactly.
One mismatch fails the gate (exit 1). The confirmation split requires the recorded approval (stage "R0").

usage: python rev1/r0_regression.py fixtures|pilot|confirmation [--workers N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import (OUT, PROFILES, REV1, SVGX, SVGX_FROZEN, check_frozen_inputs, encode_all,  # noqa: E402
                    ledger_size_results, manifest, run, sha256_bytes, stage_split_guard, write_json)

WORK = OUT / "_work" / "r0"


def check_fixtures() -> dict:
    exp = json.loads((REV1 / "fixtures" / "synthetic" / "expected.json").read_text(encoding="utf-8"))
    mism = []
    n = 0
    for f in sorted((REV1 / "fixtures" / "synthetic" / "svg").glob("*.svg")):
        new = encode_all(f, WORK / "fx_new")
        old = encode_all(f, WORK / "fx_old", exe=SVGX_FROZEN)
        n += 1
        if new["raw"] != old["raw"]:
            mism.append(f"{f.name}: raw.br differs from frozen binary")
        if new["stats"] != old["stats"]:
            mism.append(f"{f.name}: stats.json differs from frozen binary")
        e = exp["files"].get(f.stem, {}).get("streams", {})
        for p in PROFILES:
            for kind, b_new, b_old in (("svgx", new["final"][p], old["final"][p]), ("forced.svgx", new["forced"][p], old["forced"][p])):
                if b_new != b_old:
                    mism.append(f"{f.name}: {p}.{kind} differs from frozen binary")
                want = e.get(f"{p}.{kind}")
                if (want is None) != (b_new is None) or (want and want["sha256"] != sha256_bytes(b_new)):
                    mism.append(f"{f.name}: {p}.{kind} differs from expected.json")
    shutil.rmtree(WORK, ignore_errors=True)
    return {"split": "fixtures", "files": n, "mismatches": mism, "passed": not mism}


def check_file(row: dict, led: dict) -> dict:
    src = Path(row["path"])
    w = WORK / row["file_id"]
    try:
        new = encode_all(src, w)
    finally:
        pass
    mism = []
    if sha256_bytes(new["raw"]) != led["baseline_sha256"]:
        mism.append("raw.br != ledger baseline")
    for p in PROFILES:
        lp = led["profiles"][p]
        if sha256_bytes(new["final"][p]) != lp["final_sha256"]:
            mism.append(f"{p}: final stream differs")
        fs = sha256_bytes(new["forced"][p]) if new["forced"][p] is not None else None
        if fs != lp["forced_sha256"]:
            mism.append(f"{p}: forced stream differs")
    if new["stats"] != led["stats"]:
        mism.append("stats.json differs")
    shutil.rmtree(w, ignore_errors=True)
    return {"file_id": row["file_id"], "sha256": row["sha256"], "ok": not mism, "mismatches": mism,
            "G_final_len": len(new["final"]["G"]), "B": len(new["raw"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["fixtures", "pilot", "confirmation"])
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    stage_split_guard("R0", a.split)
    frozen = check_frozen_inputs()
    if not all(v["ok"] for v in frozen.values()):
        print("[R0] frozen inputs changed:", frozen)
        return 1
    versions = {"rev1": run([SVGX, "--version"]).stdout.decode().strip(),
                "frozen": run([SVGX_FROZEN, "--version"]).stdout.decode().strip()}
    if a.split == "fixtures":
        res = check_fixtures()
    else:
        rows = manifest(a.split)
        led = ledger_size_results({r["file_id"] for r in rows})
        missing = [r["file_id"] for r in rows if r["file_id"] not in led]
        if missing:
            print("[R0] files missing from the ledger:", missing[:5])
            return 1
        with ThreadPoolExecutor(a.workers) as ex:
            per = list(ex.map(lambda r: check_file(r, led[r["file_id"]]), rows))
        shutil.rmtree(WORK, ignore_errors=True)
        bad = [p for p in per if not p["ok"]]
        res = {"split": a.split, "files": len(per), "mismatches": [f"{p['file_id']}: {m}" for p in bad for m in p["mismatches"]],
               "passed": not bad, "per_file": per}
    res["versions"] = versions
    res["frozen_inputs"] = frozen
    write_json(OUT / "r0" / f"r0_{a.split}.json", res)
    print(f"[R0] {a.split}: files {res['files']}, mismatches {len(res['mismatches'])}, "
          f"{'PASSED' if res['passed'] else 'FAILED'}")
    for m in res["mismatches"][:20]:
        print("   ", m)
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

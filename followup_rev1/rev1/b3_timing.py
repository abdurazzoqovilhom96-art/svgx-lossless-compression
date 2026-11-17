"""REV1 experiment B3: algorithmic (in-process) speed (docs/PROTOCOL_REV1.md §B3).

For every file of config/b3_sample.csv (order shuffled with a fixed seed) one process runs
`svgx bench --profile G --cpu K --warmup 5 --repeats 31`: G encode (full `svgx encode` pipeline, C = min(B, S)),
G decode, raw Brotli-11 encode and raw Brotli decode, all in memory, interleaved with a rotating order, timed with
std::time::Instant. K = config/cpu_topology.json chosen P-core; HIGH priority class. During the run the Windows
power scheme is set to "High performance" (SCHEME_MIN) and restored afterwards.
CLI start-up overhead: every comparator and SVGX command on a 1-byte input, 31 runs each (not subtracted; reported).

usage: python rev1/b3_timing.py confirmation | python rev1/b3_timing.py pilot --smoke
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import (ORIG, OUT, REV1, SVGX, append_jsonl, check_frozen_inputs, ledger_size_results, manifest,  # noqa: E402
                    read_jsonl, run, stage_split_guard, write_json)

SEED = "SVGX-REV1/timing/v1"
WARMUP, REPEATS = 5, 31


def power_scheme() -> str | None:
    r = run(["powercfg", "/getactivescheme"])
    m = re.search(r"([0-9a-fA-F-]{36})", r.stdout.decode("utf-8", "replace"))
    return m.group(1) if m else None


def bench_file(path: str, cpu: int, warmup: int, repeats: int) -> dict:
    r = run([SVGX, "bench", "--profile", "G", "--cpu", str(cpu), "--warmup", str(warmup), "--repeats", str(repeats), path])
    if r.returncode != 0:
        raise RuntimeError("bench failed: " + r.stderr.decode("utf-8", "replace")[-300:])
    return json.loads(r.stdout)


def startup_overhead(reps: int) -> dict:
    """1-byte input (XWRT crashes on a zero-length input); every method's own compress and decompress plans."""
    sys.path.insert(0, str(REV1))
    import runner.toolchain as tc
    tc.TOOLS = ORIG / ".tools"
    tc.BIN = tc.TOOLS / "bin"
    tc.STAMPS = tc.TOOLS / "stamps"
    from baselines.adapters import methods
    from runner.measure import run_plan
    work = OUT / "_work" / "b3_startup"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    one = work / "one.svg"
    one.write_bytes(b"\n")
    out = {}
    for name, m in methods().items():
        ok, why = m.available()
        if not ok:
            out[name] = {"available": False, "reason": why}
            continue
        ct, dt = [], []
        for i in range(reps):
            w = work / name / str(i)
            cp = m.compress_plan(str(one), str(w / "s.out"), str(w / "c"))
            cr = run_plan(cp)
            stream = w / "stream.bin"
            shutil.copyfile(cp.produced, stream)
            dp = m.decompress_plan(str(stream), str(w / "r.out"), str(w / "d"))
            dr = run_plan(dp)
            if cr["returncode"] or dr["returncode"] or Path(dp.produced).read_bytes() != b"\n":
                raise RuntimeError(f"start-up round trip failed for {name}")
            ct.append(cr["elapsed_s"])
            dt.append(dr["elapsed_s"])
            shutil.rmtree(w, ignore_errors=True)
        out[name] = {"available": True, "compress_median_s": statistics.median(ct), "decompress_median_s": statistics.median(dt),
                     "compress_s": ct, "decompress_s": dt}
    shutil.rmtree(work, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["pilot", "confirmation"])
    ap.add_argument("--smoke", action="store_true", help="pilot only: 3 small structured files, 1 warm-up, 3 repeats")
    a = ap.parse_args()
    stage_split_guard("B3", a.split)
    if a.split == "pilot" and not a.smoke:
        sys.exit("pilot timing is only a smoke run (--smoke)")
    if not all(v["ok"] for v in check_frozen_inputs().values()):
        print("[B3] frozen inputs changed; nothing was run")
        return 1
    topo = json.loads((REV1 / "config" / "cpu_topology.json").read_text(encoding="utf-8"))
    if not topo["confirmed"]:
        print("[B3] P-core choice not confirmed; nothing was run")
        return 1
    cpu = topo["chosen_logical_processor"]
    if a.smoke:
        rows = manifest("pilot")
        led = ledger_size_results({r["file_id"] for r in rows})
        sample = sorted((dict(r, group="S") for r in rows if led[r["file_id"]]["profiles"]["G"]["invariants"]["branch"] == "structured"),
                        key=lambda r: int(r["size"]))[:3]
        warmup, repeats = 1, 3
    else:
        with open(REV1 / "config" / "b3_sample.csv", encoding="utf-8", newline="") as f:
            sample = list(csv.DictReader(f))
        paths = {r["file_id"]: r["path"] for r in manifest("confirmation")}
        for r in sample:
            r["path"] = paths[r["file_id"]]
        led = ledger_size_results({r["file_id"] for r in sample})
        warmup, repeats = WARMUP, REPEATS
    sample.sort(key=lambda r: hashlib.sha256((SEED + "/order/" + r["sha256"]).encode()).hexdigest())
    path = OUT / "b3" / (f"b3_{a.split}{'_smoke' if a.smoke else ''}.jsonl")
    done = {r["file_id"] for r in read_jsonl(path)}
    orig_scheme = power_scheme()
    switched = False
    meta = {"cpu": cpu, "power_scheme_before": orig_scheme, "warmup": warmup, "repeats": repeats}
    try:
        if not a.smoke:
            switched = run(["powercfg", "/setactive", "SCHEME_MIN"]).returncode == 0
            meta["power_scheme_during"] = power_scheme()
            meta["power_switch_ok"] = switched
        n_def = 0
        for i, r in enumerate([r for r in sample if r["file_id"] not in done], 1):
            j = bench_file(r["path"], cpu, warmup, repeats)
            lg = led[r["file_id"]]["profiles"]["G"]
            defects = []
            if not (j["restored_ok"] and j["pinned"] and j["high_priority"]):
                defects.append("bench check failed (restored/pinned/priority)")
            if j["final_len"] != lg["C"] or j["raw_len"] != led[r["file_id"]]["B"]:
                defects.append("bench stream lengths differ from the frozen ledger")
            row = {"file_id": r["file_id"], "sha256": r["sha256"], "group": r["group"], "family": r["family"],
                   "category": r["category"], "size": int(r["size"]), "defects": defects, "bench": j}
            for k in ("encode_ns", "decode_ns", "raw_encode_ns", "raw_decode_ns"):
                v = j[k]
                q = statistics.quantiles(v, n=4, method="inclusive")
                row[k.replace("_ns", "_median_ns")] = statistics.median(v)
                row[k.replace("_ns", "_iqr_ns")] = q[2] - q[0]
            append_jsonl(path, row)
            n_def += bool(defects)
            print(f"   {i} {r['file_id']} {r['group']} enc {row['encode_median_ns'] / 1e6:.1f} ms dec {row['decode_median_ns'] / 1e6:.1f} ms "
                  f"raw-dec {row['raw_decode_median_ns'] / 1e6:.1f} ms {'DEFECT ' + str(defects) if defects else ''}", flush=True)
        meta["startup_overhead"] = startup_overhead(3 if a.smoke else 31)
    finally:
        if switched and orig_scheme:
            meta["power_restore_ok"] = run(["powercfg", "/setactive", orig_scheme]).returncode == 0
            meta["power_scheme_after"] = power_scheme()
    rows = read_jsonl(path)
    meta.update(files=len(rows), defect_files=sum(bool(r["defects"]) for r in rows), complete=len(rows) == len(sample))
    write_json(path.with_name(path.stem + "_meta.json"), meta)
    print(f"[B3] {a.split}: files {meta['files']}, defects {meta['defect_files']}, complete {meta['complete']}")
    return 1 if meta["defect_files"] or not meta["complete"] else 0


if __name__ == "__main__":
    sys.exit(main())

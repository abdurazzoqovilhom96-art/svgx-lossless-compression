"""REV1 experiment B2: strong comparators and a strong back end (docs/PROTOCOL_REV1.md §B2).

Per file (every stream is decoded again and compared with the original bytes):
  P      paq8px v217 at the calibrated level (config/paq_calibration.json), whole file
  PU     paq8px on the literal stream U of the frozen forced G stream (eligible files only)
  S_P    = |S_G| - |Br(U)| + |P(U)|  (hybrid structured container; other sections unchanged, already verified by R0)
  H      = min(P, S_P) on eligible files, P otherwise (0-byte discrimination: paq8px archives start with b"paq8px")
  ZD     zstd 1.5.7 -19 --single-thread with the pilot-trained dictionary (config/zstd_pilot.dict)
  BA     brotli 1.2.1 -q 11, CLI default window (auto-sized to the file, <= 24)
  BL     brotli 1.2.1 -q 11 --large_window=30 (large-window extension)
usage: python rev1/b2_baselines.py pilot|confirmation [--workers N] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import (BROTLI_EXE, OUT, REV1, RUN, ZSTD_EXE, append_jsonl, check_frozen_inputs, ledger_size_results,  # noqa: E402
                    manifest, read_jsonl, run, sha256_bytes, stage_split_guard, write_json)
import paq  # noqa: E402
import sections  # noqa: E402

DICT = REV1 / "config" / "zstd_pilot.dict"
CAL = REV1 / "config" / "paq_calibration.json"


def tool_roundtrip(name: str, data: bytes, work: Path, cargs: list, dargs: list) -> dict:
    """Generic file-to-file round trip: tool cargs IN OUT, tool dargs OUT RESTORED."""
    work.mkdir(parents=True, exist_ok=True)
    i, o, r = work / f"{name}.in", work / f"{name}.out", work / f"{name}.restored"
    i.write_bytes(data)
    c = run([*cargs, "-o", o, i])
    if c.returncode != 0 or not o.exists():
        return {"ok": False, "error": c.stderr.decode("utf-8", "replace")[-300:]}
    d = run([*dargs, "-o", r, o])
    ok = d.returncode == 0 and r.exists() and r.read_bytes() == data
    res = {"ok": ok, "len": o.stat().st_size, "first_byte": o.read_bytes()[:1].hex()}
    if not ok:
        res["error"] = d.stderr.decode("utf-8", "replace")[-300:]
    for p in (i, o, r):
        if p.exists():
            p.unlink()
    return res


def run_file(row: dict, led: dict, level: int) -> dict:
    src = Path(row["path"])
    x = src.read_bytes()
    w = OUT / "_work" / "b2" / row["file_id"]
    out = {"file_id": row["file_id"], "sha256": row["sha256"], "family": row["family"], "category": row["category"],
           "size": len(x), "B": led["B"], "C_G": led["profiles"]["G"]["C"], "paq_level": level, "defects": []}
    d = out["defects"]
    try:
        p = paq.roundtrip(x, level, w / "paq_x")
        out["paq_x"] = p
        if not p["ok"]:
            d.append(f"paq8px(x) failed: {p.get('error', 'round trip / magic')}")
        out["P"] = p.get("len")
        lg = led["profiles"]["G"]
        out["eligible"] = lg["forced_sha256"] is not None
        if out["eligible"]:
            fpath = RUN / led["stream_dir"] / "G.forced.svgx"
            forced = fpath.read_bytes()
            if sha256_bytes(forced) != lg["forced_sha256"]:
                d.append("frozen forced G stream hash mismatch")
            ex = sections.extract(forced)
            if ex["restored"] != x:
                d.append("reference decoder did not restore the original")
            h = ex["header"]
            pu = paq.roundtrip(ex["U"], level, w / "paq_u")
            out["paq_U"] = pu
            if not pu["ok"]:
                d.append(f"paq8px(U) failed: {pu.get('error', 'round trip / magic')}")
            out.update(S_G=len(forced), U_len=len(ex["U"]), literal_len=h["literal_len"], PU=pu.get("len"))
            if pu.get("len") is not None:
                out["S_P"] = len(forced) - h["literal_len"] + pu["len"]
                parts = 60 + pu["len"] + h["schedule_len"] + h["geometry_len"] + h["spelling_len"] + h["escape_len"]
                if out["S_P"] != parts:
                    d.append("S_P does not reconcile with its sections")
        else:
            out["S_P"] = None
        if out.get("P") is not None:
            out["H"] = min(out["P"], out["S_P"]) if out.get("S_P") is not None else out["P"]
            out["H_branch"] = "hybrid" if out["H"] != out["P"] else "paq8px"
            if out["H"] > out["P"]:
                d.append("invariant H <= P violated")
        zd = tool_roundtrip("zd", x, w, [ZSTD_EXE, "-19", "--single-thread", "-q", "-f", "-D", DICT],
                            [ZSTD_EXE, "-d", "-q", "-f", "-D", DICT])
        ba = tool_roundtrip("ba", x, w, [BROTLI_EXE, "-q", "11", "-f"], [BROTLI_EXE, "-d", "-f"])
        bl = tool_roundtrip("bl", x, w, [BROTLI_EXE, "-q", "11", "--large_window=30", "-f"],
                            [BROTLI_EXE, "-d", "--large_window=30", "-f"])
        for k, v in (("ZD", zd), ("BA", ba), ("BL", bl)):
            out[k] = v.get("len")
            out[f"{k}_check"] = v
            if not v["ok"]:
                d.append(f"{k} round trip failed: {v.get('error')}")
    except Exception as e:
        d.append(f"exception: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(w, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["pilot", "confirmation"])
    ap.add_argument("--workers", type=int, default=0, help="0 = from calibration (24 GiB / max peak)")
    ap.add_argument("--limit", type=int, default=0, help="pilot only: first N files by size order (smoke run)")
    a = ap.parse_args()
    stage_split_guard("B2", a.split)
    if a.limit and a.split != "pilot":
        sys.exit("--limit is for pilot smoke runs only")
    if not all(v["ok"] for v in check_frozen_inputs().values()):
        print("[B2] frozen inputs changed; nothing was run")
        return 1
    cal = json.loads(CAL.read_text(encoding="utf-8"))
    level = cal["chosen_level"]
    peak = cal["levels"][str(level)]["max_peak_bytes"]
    workers = a.workers or max(1, int((24 << 30) // max(peak, 1)))
    rows = manifest(a.split)
    led = ledger_size_results({r["file_id"] for r in rows})
    rows.sort(key=lambda r: -int(r["size"]))          # longest jobs first
    if a.limit:  # smoke: the smallest files with and without a forced G stream (exercises both H branches)
        by = sorted(rows, key=lambda r: (int(r["size"]), r["sha256"]))
        el = [r for r in by if led[r["file_id"]]["profiles"]["G"]["forced_sha256"]]
        ne = [r for r in by if not led[r["file_id"]]["profiles"]["G"]["forced_sha256"]]
        rows = el[:(a.limit + 1) // 2] + ne[:a.limit // 2]
    path = OUT / "b2" / (f"b2_{a.split}.jsonl" if not a.limit else f"b2_{a.split}_smoke.jsonl")
    done = {r["file_id"] for r in read_jsonl(path)}
    todo = [r for r in rows if r["file_id"] not in done]
    print(f"[B2] {a.split}: level {level}, workers {workers}, {len(rows)} files, {len(todo)} to run", flush=True)
    with ProcessPoolExecutor(workers) as ex:
        futs = {ex.submit(run_file, r, led[r["file_id"]], level): r for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            res = f.result()
            append_jsonl(path, res)
            if res["defects"]:
                print(f"   DEFECT {res['file_id']}: {res['defects'][:3]}", flush=True)
            if i % 25 == 0:
                print(f"   {i}/{len(todo)}", flush=True)
    allrows = read_jsonl(path)
    summ = {"split": a.split, "files": len(allrows), "defect_files": sum(bool(r["defects"]) for r in allrows),
            "complete": len(allrows) == len(rows), "paq_level": level, "workers": workers,
            "max_paq_peak_bytes": max((max(r["paq_x"]["compress"]["peak_memory_bytes"], r.get("paq_U", {}).get("compress", {}).get("peak_memory_bytes", 0))
                                       for r in allrows if "paq_x" in r), default=None)}
    write_json(path.with_name(path.stem + "_summary.json"), summ)
    print(f"[B2] {summ}")
    return 1 if summ["defect_files"] or not summ["complete"] else 0


if __name__ == "__main__":
    sys.exit(main())

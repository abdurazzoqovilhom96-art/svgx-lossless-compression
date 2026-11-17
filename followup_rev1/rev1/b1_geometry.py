"""REV1 experiment B1: contribution of geometric prediction (docs/PROTOCOL_REV1.md §B1).

Arms per file (all with the G spelling model; final output C = min(B, S), ties -> raw, as in the codec):
  B     raw Brotli-11 (ledger baseline, re-checked by R0)
  T     holes as text in one extra Brotli stream (separation only)            [sections.py]
  Z     hole values X as written, exp-Golomb, no prediction                   [sections.py]
  D0    codec, --modes 00
  M01   codec, --modes 00,01
  M010  codec, --modes 00,01,10
  F     codec, all modes (= frozen G; must equal the ledger byte for byte)
Files without a modelled block have no structured stream: every arm equals B (no geometry code path runs).

Per-file checks (any failure -> defect, exit 1): restricted-mode forced streams decoded by both decoders;
literal/schedule/spelling/escape sections identical to F; S_F <= S_M010 <= S_M01 <= S_D0 and
C_F <= C_M010 <= C_M01 <= C_D0 <= B; C = min(B, S) reproduced; T and Z round trips exact; F == ledger.

usage: python rev1/b1_geometry.py pilot|confirmation [--workers N]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import (OUT, append_jsonl, check_frozen_inputs, encode_all, ledger_size_results, manifest,  # noqa: E402
                    read_jsonl, sha256_bytes, stage_split_guard, svgx_raw_bytes, verify_stream, write_json)
import sections  # noqa: E402

ARMS = [("D0", "00"), ("M01", "00,01"), ("M010", "00,01,10")]


def final_rule(B: int, S: int | None) -> int:
    return S if (S is not None and S < B) else B


def run_file(row: dict, led: dict) -> dict:
    src = Path(row["path"])
    original = src.read_bytes()
    w = OUT / "_work" / "b1" / row["file_id"]
    B = led["B"]
    out = {"file_id": row["file_id"], "sha256": row["sha256"], "family": row["family"], "category": row["category"],
           "size": int(row["size"]), "B": B, "defects": []}
    d = out["defects"]
    lg = led["profiles"]["G"]
    out["C_F_ledger"] = lg["C"]
    if lg["forced_sha256"] is None:
        out["eligible"] = False
        for k in ("F", "D0", "M01", "M010", "T", "Z"):
            out[f"C_{k}"] = B
            out[f"S_{k}"] = None
        if lg["C"] != B:
            d.append("ineligible file whose ledger G output is not the raw stream")
        return out
    out["eligible"] = True
    try:
        F = encode_all(src, w / "F")
        if sha256_bytes(F["final"]["G"]) != lg["final_sha256"] or sha256_bytes(F["forced"]["G"]) != lg["forced_sha256"]:
            d.append("F differs from the frozen ledger")
        if len(F["raw"]) != B:
            d.append("raw length differs from ledger B")
        hF = sections.parse_header(F["forced"]["G"])
        out["S_F"], out["C_F"] = len(F["forced"]["G"]), len(F["final"]["G"])
        out["geometry_bits_F"] = F["stats"]["common"]["geometry_bits"]
        out["mode_counts_F"] = F["stats"]["common"]["mode_counts"]
        out["hole_count"] = F["stats"]["common"]["hole_count"]
        for name, modes in ARMS:
            A = encode_all(src, w / name, modes)
            s, c = A["forced"]["G"], A["final"]["G"]
            if s is None:
                d.append(f"{name}: no forced stream")
                continue
            h = sections.parse_header(s)
            for sec in ("literal_bytes", "schedule_bytes", "spelling_bytes", "escape_bytes"):
                if h[sec] != hF[sec]:
                    d.append(f"{name}: {sec} differs from F")
            mc = A["stats"]["common"]["mode_counts"]
            allowed = {"D0": [0], "M01": [0, 1], "M010": [0, 1, 2]}[name]
            if any(mc[m] for m in range(4) if m not in allowed):
                d.append(f"{name}: disallowed mode used {mc}")
            out[f"S_{name}"], out[f"C_{name}"] = len(s), len(c)
            out[f"geometry_bits_{name}"] = A["stats"]["common"]["geometry_bits"]
            out[f"mode_counts_{name}"] = mc
            if len(c) != final_rule(B, len(s)):
                d.append(f"{name}: C != min(B, S)")
            v = verify_stream(s, original, w / "v")
            if not (v["native_ok"] and v["reference_ok"]):
                d.append(f"{name}: forced stream round trip failed {v}")
            if c != s:  # final is the raw stream; it must be the ledger baseline
                if sha256_bytes(c) != led["baseline_sha256"]:
                    d.append(f"{name}: raw final differs from baseline")
        tz = sections.tz_arms(F["forced"]["G"], original, lambda b: svgx_raw_bytes(b, w / "br"))
        out.update({k: v for k, v in tz.items() if k not in ("S_T", "S_Z")})
        out["S_T"], out["S_Z"] = tz["S_T"], tz["S_Z"]
        out["C_T"], out["C_Z"] = final_rule(B, tz["S_T"]), final_rule(B, tz["S_Z"])
        if not (tz["T_roundtrip_ok"] and tz["Z_roundtrip_ok"]):
            d.append("T/Z round trip failed")
        if all(f"S_{k}" in out for k in ("D0", "M01", "M010")):
            sc = [out["S_D0"], out["S_M01"], out["S_M010"], out["S_F"]]
            cc = [B, out["C_D0"], out["C_M01"], out["C_M010"], out["C_F"]]
            if any(x < y for x, y in zip(sc, sc[1:])):
                d.append(f"monotonicity violated (S) {sc}")
            if any(x < y for x, y in zip(cc, cc[1:])):
                d.append(f"monotonicity violated (C) {cc}")
    except Exception as e:  # recorded as a defect; never silently dropped
        d.append(f"exception: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(w, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["pilot", "confirmation"])
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    stage_split_guard("B1", a.split)
    if not all(v["ok"] for v in check_frozen_inputs().values()):
        print("[B1] frozen inputs changed; nothing was run")
        return 1
    rows = manifest(a.split)
    led = ledger_size_results({r["file_id"] for r in rows})
    path = OUT / "b1" / f"b1_{a.split}.jsonl"
    done = {r["file_id"] for r in read_jsonl(path)}
    todo = [r for r in rows if r["file_id"] not in done]
    print(f"[B1] {a.split}: {len(rows)} files, {len(done)} already done, {len(todo)} to run")
    n_def = 0
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_file, r, led[r["file_id"]]) for r in todo]
        for i, f in enumerate(futs, 1):
            res = f.result()
            append_jsonl(path, res)
            if res["defects"]:
                n_def += 1
                print(f"   DEFECT {res['file_id']}: {res['defects'][:3]}")
            if i % 50 == 0:
                print(f"   {i}/{len(todo)}")
    allrows = read_jsonl(path)
    defects = [r for r in allrows if r["defects"]]
    summ = {"split": a.split, "files": len(allrows), "eligible": sum(r["eligible"] for r in allrows),
            "defect_files": len(defects), "complete": len(allrows) == len(rows)}
    write_json(OUT / "b1" / f"b1_{a.split}_summary.json", summ)
    print(f"[B1] {a.split}: {summ}")
    return 1 if defects or not summ["complete"] else 0


if __name__ == "__main__":
    sys.exit(main())

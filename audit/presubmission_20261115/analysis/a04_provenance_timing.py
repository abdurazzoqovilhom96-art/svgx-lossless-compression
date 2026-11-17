"""A12/A13/A14: provenance (bound files vs freeze, timeline) and timing/memory audit. No codec jobs.

Reads the frozen run read-only and writes ../derived/a04_results.json and ../derived/timing_per_file.csv.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])           # SVG_EXPERIMENT
RUN = ROOT / "results" / "20261114_050438_SVGX-2026-11-A"
D = Path(__file__).resolve().parent.parent / "derived"
out: dict = {}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---- A14: bound files now vs freeze; run copy of freeze vs state copy
fz = json.loads((RUN / "01_protocol" / "freeze.json").read_text(encoding="utf-8"))
changed, missing = [], []
for rel, h in fz["bound_files"].items():
    p = ROOT / rel
    if not p.exists():
        missing.append(rel)
    elif sha(p) != h:
        changed.append(rel)
out["A14_bound_files"] = {"count": len(fz["bound_files"]), "changed_since_freeze": changed, "missing": missing,
                          "frozen_utc": fz["frozen_utc"], "build_id": fz["build_id"]}
out["A14_freeze_copy_equal_state"] = sha(RUN / "01_protocol" / "freeze.json") == sha(ROOT / "state" / "freeze.json")
out["A14_run_manifests_equal_frozen"] = {s: sha(RUN / "02_corpus" / f"{s}.csv") == fz["bound_files"][f"data/manifests/{s}.csv"]
                                         for s in ("pilot", "confirmation")}
pkg = RUN.parent / (RUN.name + "__package.zip")
out["A14_package"] = {"sha256": sha(pkg), "verify_json": json.loads((RUN.parent / (RUN.name + "__package.verify.json")).read_text(encoding="utf-8"))}
# originals and stored streams present?
man = {s: list(csv.DictReader(open(RUN / "02_corpus" / f"{s}.csv", encoding="utf-8"))) for s in ("pilot", "confirmation")}
present = sum(1 for s in man for m in man[s] if (ROOT / m["original"]).exists())
# raw SHA-256 of every original must equal its manifest hash (input identity of every measurement)
bad = [m["file_id"] for s in man for m in man[s] if (ROOT / m["original"]).exists() and sha(ROOT / m["original"]) != m["sha256"]]
out["A14_originals_sha_mismatch"] = bad
out["A14_originals_present"] = f"{present}/{sum(len(v) for v in man.values())}"

# ---- A12: timeline
appr = json.loads((RUN / "01_protocol" / "approval.json").read_text(encoding="utf-8"))
pdec = json.loads((RUN / "07_statistics" / "pilot_decision.json").read_text(encoding="utf-8"))
con = sqlite3.connect(f"file:{RUN / 'ledger.sqlite'}?mode=ro&immutable=1", uri=True)
tl = {}
for split, task, mn, mx in con.execute(
        "select j.split, j.task, min(a.started_utc), max(a.finished_utc) from attempts a join jobs j on a.key=j.key group by j.split, j.task"):
    tl[f"{split}/{task}"] = [mn, mx]
out["A12_timeline"] = {"frozen_utc": fz["frozen_utc"],
                       "approval": {k: appr.get(k) for k in ("decision", "scope", "utc", "recorded_utc", "freeze_sha256") if k in appr},
                       "pilot_decision_utc": pdec["recorded_utc"], "jobs": tl,
                       "single_build_id": [r[0] for r in con.execute("select distinct build_id from jobs")]}
last_pilot_id = con.execute("select max(a.id) from attempts a join jobs j on a.key=j.key where j.split='pilot'").fetchone()[0]
first_conf_id = con.execute("select min(a.id) from attempts a join jobs j on a.key=j.key where j.split='confirmation'").fetchone()[0]
conf_first = tl.get("confirmation/size", [None])[0]
out["A12_order"] = {"last_pilot_attempt_id": last_pilot_id, "first_confirmation_attempt_id": first_conf_id,
                    "pilot_decision_utc": pdec["recorded_utc"], "first_confirmation_start_utc": conf_first,
                    "confirmation_after_all_pilot_jobs": first_conf_id > last_pilot_id,
                    "confirmation_not_before_decision_second": bool(conf_first and conf_first >= pdec["recorded_utc"]),
                    "note": "runner/controller.py writes the decision between the pilot and confirmation loops (sequential)"}

# ---- A13: timing
per = defaultdict(lambda: {"c": [], "d": [], "mc": [], "md": [], "split": None})
for key, method, split, result in con.execute("select key, method, split, result from jobs where task='timing'"):
    r = json.loads(result)
    if not r.get("available") or r.get("warmup"):
        continue
    sha256 = key.split("|")[1]
    k = (method, sha256)
    per[k]["c"].append(r["compress"]["elapsed_s"])
    per[k]["d"].append(r["decompress"]["elapsed_s"])
    per[k]["mc"].append(r["compress"]["peak_memory_bytes"])
    per[k]["md"].append(r["decompress"]["peak_memory_bytes"])
    per[k]["split"] = split
pf = {r["sha256"]: r for r in csv.DictReader(open(D / "per_file_from_ledger.csv", encoding="utf-8"))}
files = sorted({s for (_, s) in per})
methods = sorted({m for (m, _) in per})
rows = []
for s in files:
    base = pf[s]
    row = {"sha256": s, "split": per[("svgx_G", s)]["split"], "file_id": base["file_id"], "category": base["category"],
           "orig_len": int(base["orig_len"]), "branch_G": base["branch_G"], "eligible": base["eligible"]}
    for m in methods:
        v = per.get((m, s))
        if v:
            row[f"{m}_enc_med_s"] = statistics.median(v["c"])
            row[f"{m}_dec_med_s"] = statistics.median(v["d"])
            row[f"{m}_n"] = len(v["c"])
            row[f"{m}_enc_cv"] = statistics.pstdev(v["c"]) / statistics.mean(v["c"])
            row[f"{m}_peak"] = max(v["mc"] + v["md"])
    rows.append(row)
with open(D / "timing_per_file.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

MiB = 1 << 20
summ = {}
for m in methods:
    have = [r for r in rows if f"{m}_enc_med_s" in r]
    nbytes = sum(r["orig_len"] for r in have)
    summ[m] = {"files": len(have), "min_repeats": min(r[f"{m}_n"] for r in have),
               "pooled_enc_MiB_s": nbytes / MiB / sum(r[f"{m}_enc_med_s"] for r in have),
               "pooled_dec_MiB_s": nbytes / MiB / sum(r[f"{m}_dec_med_s"] for r in have),
               "median_per_file_enc_s": statistics.median(r[f"{m}_enc_med_s"] for r in have),
               "median_per_file_dec_s": statistics.median(r[f"{m}_dec_med_s"] for r in have),
               "median_repeat_cv_enc": statistics.median(r[f"{m}_enc_cv"] for r in have),
               "peak_bytes_median": statistics.median(r[f"{m}_peak"] for r in have),
               "peak_bytes_max": max(r[f"{m}_peak"] for r in have)}
out["A13_timing_summary_recomputed"] = summ
comp = {}
for name, subset in (("all", rows), ("G_structured", [r for r in rows if r["branch_G"] == "structured"]),
                     ("G_raw", [r for r in rows if r["branch_G"] == "raw"]),
                     ("over_64KiB", [r for r in rows if r["orig_len"] >= 65536])):
    if not subset:
        continue
    d = {"files": len(subset), "bytes": sum(r["orig_len"] for r in subset)}
    for other in ("brotli11", "svgx_P"):
        enc_ratio = [r["svgx_G_enc_med_s"] / r[f"{other}_enc_med_s"] for r in subset]
        dec_ratio = [r["svgx_G_dec_med_s"] / r[f"{other}_dec_med_s"] for r in subset]
        sum_enc_G = sum(r["svgx_G_enc_med_s"] for r in subset)
        sum_enc_O = sum(r[f"{other}_enc_med_s"] for r in subset)
        sum_dec_G = sum(r["svgx_G_dec_med_s"] for r in subset)
        sum_dec_O = sum(r[f"{other}_dec_med_s"] for r in subset)
        be = None
        if sum_dec_O > sum_dec_G:
            be = (sum_enc_G - sum_enc_O) / (sum_dec_O - sum_dec_G)
        d[f"G_vs_{other}"] = {"median_enc_time_ratio": statistics.median(enc_ratio), "median_dec_time_ratio": statistics.median(dec_ratio),
                              "pooled_enc_time_ratio": sum_enc_G / sum_enc_O, "pooled_dec_time_ratio": sum_dec_G / sum_dec_O,
                              "files_G_decodes_faster": sum(1 for x in dec_ratio if x < 1),
                              "pooled_K_break_even_decodes": be,
                              "note": "K* = (enc_G - enc_other)/(dec_other - dec_G) on the same files (sums of per-file medians); None if G does not decode faster in total"}
    comp[name] = d
out["A13_paired_time_comparisons"] = comp
# python reference decoder time recorded during the size pass (not part of timing)
ref = []
for (result,) in con.execute("select result from jobs where task='size' and method='svgx'"):
    r = json.loads(result)
    ref.append(r["profiles"]["G"]["verify_final"]["reference_elapsed_s"])
out["A13_reference_decoder_elapsed_s_G_final"] = {"files": len(ref), "median": statistics.median(ref), "max": max(ref)}
(D / "a04_results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))

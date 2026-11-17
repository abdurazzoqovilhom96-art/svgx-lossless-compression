"""A01/A02/A03/A04: independent recomputation from the frozen ledger (read-only), no codec jobs.

Reads  results/<run>/ledger.sqlite (mode=ro, immutable), 02_corpus/{pilot,confirmation}.csv,
       10_tables/<split>_main_comparisons.csv (for comparison only).
Writes ../derived/per_file_from_ledger.csv, ../derived/recomputed_comparisons.csv, ../derived/checks_a02.json
Does not import project code (independent of reporting/build.py and reporting/stats.py).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import statistics
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

RUN = Path(sys.argv[1])
OUT = Path(__file__).resolve().parent.parent / "derived"
OUT.mkdir(exist_ok=True)
PROFILES = ["D", "P", "I", "U", "G"]
SIZE_EXTERNAL = ["xwrt_l6", "xz9e", "ppmd7z", "zstd19", "gzip9"]
H0 = 60

con = sqlite3.connect(f"file:{RUN / 'ledger.sqlite'}?mode=ro&immutable=1", uri=True)
jobs = defaultdict(dict)
job_methods = Counter()
for split, sha, method, task, status, result in con.execute(
        "select split, input_sha256, method, task, status, result from jobs"):
    job_methods[(task, split, method, status)] += 1
    if task == "size" and status == "done":
        jobs[(split, sha)][method] = json.loads(result)

checks: dict = {"run": str(RUN), "job_counts": {"|".join(k): v for k, v in sorted(job_methods.items())}}
problems: list[str] = []
rows = []
for split in ("pilot", "confirmation"):
    with open(RUN / "02_corpus" / f"{split}.csv", newline="", encoding="utf-8") as f:
        man = list(csv.DictReader(f))
    shas = [m["sha256"] for m in man]
    checks[f"{split}_manifest_files"] = len(man)
    checks[f"{split}_duplicate_sha_in_manifest"] = len(shas) - len(set(shas))
    for m in man:
        res = jobs.get((split, m["sha256"]), {})
        sv = res.get("svgx")
        if sv is None:
            problems.append(f"{split} {m['file_id']}: no svgx size result")
            continue
        row = OrderedDict(file_id=m["file_id"], split=split, sha256=m["sha256"], category=m["category"],
                          family=m["family"], orig_len=int(m["size"]), B=sv["B"])
        # independent brotli.exe stream vs codec raw branch
        br = res.get("brotli11")
        row["brotli_job_len"] = br["len"] if br else ""
        row["brotli_job_roundtrip_ok"] = bool(br and br.get("roundtrip_ok"))
        row["B_equals_brotli_job"] = bool(br and br["len"] == sv["B"] and br["sha256"] == sv["baseline_sha256"])
        restored_all = True
        for p in PROFILES:
            pp = sv["profiles"][p]
            inv = pp["invariants"]
            secs = pp["forced_sections"]
            if secs is None:  # file has no modeled block: no structured stream exists (S = infinity)
                forced_len = None
                o_val = sv["B"]
                row[f"spell_{p}"] = ""
                row[f"escsec_{p}"] = ""
            else:
                forced_len = H0 + sum(secs[s]["len"] for s in ("literals", "schedule", "geometry", "spelling", "escapes"))
                o_val = min(sv["B"], H0 + secs["literals"]["len"] + secs["schedule"]["len"] + secs["geometry"]["len"])
                row[f"spell_{p}"] = secs["spelling"]["len"]
                row[f"escsec_{p}"] = secs["escapes"]["len"]
            row[f"C_{p}"] = pp["C"]
            row[f"F_{p}"] = "" if forced_len is None else forced_len
            row[f"branch_{p}"] = inv["branch"]
            row[f"O_{p}"] = o_val
            # encoder rule C = min(B, S), ties -> raw
            exp_c = forced_len if (forced_len is not None and forced_len < sv["B"]) else sv["B"]
            exp_branch = "structured" if (forced_len is not None and forced_len < sv["B"]) else "raw"
            if inv["forced_len"] is not None and inv["forced_len"] != forced_len:
                problems.append(f"{m['file_id']} {p}: forced_len {inv['forced_len']} != sections {forced_len}")
            if pp["C"] != exp_c or inv["branch"] != exp_branch:
                problems.append(f"{m['file_id']} {p}: C={pp['C']} branch={inv['branch']} expected {exp_c}/{exp_branch}")
            if inv["branch"] == "raw" and pp["final_sha256"] != sv["baseline_sha256"]:
                problems.append(f"{m['file_id']} {p}: raw branch not byte-equal to independent Brotli stream")
            for kind in ("verify_final", "verify_forced"):
                v = pp.get(kind)
                if v is None:
                    continue
                ok = (v["native_ok"] and v["reference_ok"] and v["native_sha256"] == m["sha256"]
                      and v["reference_sha256"] == m["sha256"] and v["len"] == (pp["C"] if kind == "verify_final" else forced_len))
                if not ok:
                    restored_all = False
                    problems.append(f"{m['file_id']} {p} {kind}: restoration not verified")
        os_ = {row[f"O_{p}"] for p in PROFILES}
        if len(os_) != 1:
            problems.append(f"{m['file_id']}: O differs across profiles {os_}")
        row["O"] = min(os_)
        row["eligible"] = sv["stats"]["eligible"]
        row["file_reason"] = sv["stats"]["file_reason"] or ""
        row["blocks"] = sv["stats"]["blocks"]
        row["common_sections_equal"] = sv["common_sections_equal"]
        row["escape_equal_IUG"] = sv["escape_equal_IUG"]
        row["restored_both_decoders_all_arms"] = restored_all
        for e in SIZE_EXTERNAL:
            er = res.get(e)
            row[f"E_{e}"] = er["len"] if (er and er.get("available") and er.get("roundtrip_ok")) else ""
            if row[f"E_{e}"] == "":
                problems.append(f"{m['file_id']}: external {e} missing or failed round trip")
        rows.append(row)

cols = list(rows[0].keys())
with open(OUT / "per_file_from_ledger.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

# cross-split independence
for key in ("sha256", "family"):
    a = {r[key] for r in rows if r["split"] == "pilot"}
    b = {r[key] for r in rows if r["split"] == "confirmation"}
    checks[f"cross_split_overlap_{key}"] = len(a & b)


def comp(rs, a, c):
    sa = sum(int(r[a]) for r in rs)
    sc = sum(int(r[c]) for r in rs)
    wins = sum(1 for r in rs if int(r[c]) < int(r[a]))
    ties = sum(1 for r in rs if int(r[c]) == int(r[a]))
    fam = defaultdict(int)
    for r in rs:
        fam[r["family"]] += int(r[a]) - int(r[c])
    fw = sum(1 for g in fam.values() if g > 0)
    ft = sum(1 for g in fam.values() if g == 0)
    med = statistics.median(100.0 * (int(r[a]) - int(r[c])) / int(r[a]) for r in rs)
    return dict(files=len(rs), sum_A=sa, sum_C=sc, gain_bytes=sa - sc, gain_percent=100.0 * (sa - sc) / sa,
                file_median_gain_percent=med, file_wins=wins, file_ties=ties, file_losses=len(rs) - wins - ties,
                family_wins=fw, family_ties=ft, family_losses=len(fam) - fw - ft, families=len(fam))


pairs = {"G_vs_brotli11": ("B", "C_G"), "G_vs_U": ("C_U", "C_G"), "G_vs_I": ("C_I", "C_G"), "G_vs_D": ("C_D", "C_G"),
         "G_vs_P": ("C_P", "C_G"), "P_vs_D": ("C_D", "C_P"), "U_vs_I": ("C_I", "C_U"),
         **{f"{p}_vs_brotli11": ("B", f"C_{p}") for p in ["D", "P", "I", "U"]},
         **{f"G_vs_{e}": (f"E_{e}", "C_G") for e in SIZE_EXTERNAL}}
out_rows = []
diffs = []
for split in ("pilot", "confirmation"):
    rs = [r for r in rows if r["split"] == split]
    rep = {}
    with open(RUN / "10_tables" / f"{split}_main_comparisons.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rep[r["comparison"]] = r
    cstar = json.loads((RUN / "07_statistics" / "pilot_decision.json").read_text(encoding="utf-8"))["cstar"]["selected"]
    allpairs = dict(pairs, G_vs_Cstar=(f"C_{cstar}", "C_G"))
    for name, (a, c) in allpairs.items():
        d = comp(rs, a, c)
        out_rows.append({"split": split, "comparison": name, **d})
        if name in rep:
            r = rep[name]
            for k_rep, k_new in (("sum_A", "sum_A"), ("sum_C", "sum_C"), ("file_wins", "file_wins"), ("file_ties", "file_ties"),
                                 ("file_losses", "file_losses"), ("family_wins", "family_wins"), ("family_ties", "family_ties"),
                                 ("family_losses", "family_losses"), ("files", "files")):
                if int(r[k_rep]) != d[k_new]:
                    diffs.append(f"{split} {name} {k_rep}: report {r[k_rep]} vs recomputed {d[k_new]}")
            if abs(float(r["gain_percent"]) - round(d["gain_percent"], 4)) > 0.00005:
                diffs.append(f"{split} {name} gain: report {r['gain_percent']} vs {d['gain_percent']:.6f}")
    # pooled ceiling, forced, fallback
    sb = sum(r["B"] for r in rs)
    so = sum(r["O"] for r in rs)
    checks[f"{split}_ceiling_percent"] = 100.0 * (sb - so) / sb
    for p in PROFILES:
        el = [r for r in rs if r[f"F_{p}"] != ""]
        gains = sum(max(0, r["B"] - r[f"F_{p}"]) for r in el)
        losses = sum(max(0, r[f"F_{p}"] - r["B"]) for r in el)
        checks[f"{split}_forced_{p}"] = {"files_with_structured_stream": len(el), "gross_gain": gains,
                                         "gross_loss": losses, "net_B_minus_forced": gains - losses,
                                         "structured_files": sum(1 for r in rs if r[f"branch_{p}"] == "structured")}
    checks[f"{split}_files"] = len(rs)
    checks[f"{split}_eligible_files"] = sum(1 for r in rs if r["eligible"])
    checks[f"{split}_ineligible_reasons"] = dict(Counter(r["file_reason"] for r in rs if not r["eligible"]))
    checks[f"{split}_restored_all_arms_both_decoders"] = sum(1 for r in rs if r["restored_both_decoders_all_arms"])
    checks[f"{split}_B_equals_independent_brotli"] = sum(1 for r in rs if r["B_equals_brotli_job"])

with open(OUT / "recomputed_comparisons.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    w.writerows(out_rows)
checks["report_vs_recomputed_differences"] = diffs
checks["problems"] = problems[:200]
checks["problem_count"] = len(problems)
(OUT / "checks_a02.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in checks.items() if k != "job_counts"}, indent=1))

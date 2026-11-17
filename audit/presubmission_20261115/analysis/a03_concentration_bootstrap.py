"""A09/A10/A11/A07: concentration, sensitivity and bootstrap audit from ../derived/per_file_from_ledger.csv.
No codec jobs. Post-hoc analyses are labelled as such in the output.

1. Reproduces the frozen family bootstrap (PROTOCOL §5: whole families, PCG64 seed 20261113, 50 000 draws,
   chunks of 2000, families sorted by id, linear quantiles) with an independent implementation.
2. Post-hoc sensitivity: Monte-Carlo spread of the endpoints over 20 other seeds; file-level (non-clustered)
   bootstrap for contrast; number of draws beyond each Bonferroni quantile.
3. Concentration: per-family / per-file contribution to G vs Brotli saving, top-k shares, leave-one-family-out,
   leave-top-k-out, equal-family mean, by category and by size bracket.
4. Mechanism decomposition: B - O (geometry/literal saving with free spelling), spelling cost per arm.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import OrderedDict, defaultdict
from pathlib import Path

import numpy as np

D = Path(__file__).resolve().parent.parent / "derived"
rows = [r for r in csv.DictReader(open(D / "per_file_from_ledger.csv", encoding="utf-8"))]
for r in rows:
    for k in ("B", "O", "orig_len", "C_D", "C_P", "C_I", "C_U", "C_G"):
        r[k] = int(r[k])
conf = [r for r in rows if r["split"] == "confirmation"]
out: dict = {}

CONTRASTS = OrderedDict([("G_vs_Cstar", ("C_P", "C_G")), ("G_vs_U", ("C_U", "C_G")), ("G_vs_brotli11", ("B", "C_G")),
                         ("G_vs_I", ("C_I", "C_G")), ("G_vs_D", ("C_D", "C_G")), ("G_vs_P", ("C_P", "C_G"))])


def fam_sums(rs, a, c):
    fam = OrderedDict()
    for r in sorted(rs, key=lambda r: (r["family"], r["file_id"])):
        fam.setdefault(r["family"], [0, 0])
        fam[r["family"]][0] += r[a]
        fam[r["family"]][1] += r[c]
    return fam


def boot(rs, seed, resamples=50000, chunk=2000, unit="family"):
    if unit == "family":
        groups = list(fam_sums(rs, "B", "B").keys())
        arrs = {n: np.array(list(fam_sums(rs, a, c).values()), dtype=np.float64) for n, (a, c) in CONTRASTS.items()}
    else:
        arrs = {n: np.array([[r[a], r[c]] for r in sorted(rs, key=lambda r: (r["family"], r["file_id"]))], dtype=np.float64)
                for n, (a, c) in CONTRASTS.items()}
    m = len(next(iter(arrs.values())))
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = {n: np.empty(resamples) for n in CONTRASTS}
    done = 0
    while done < resamples:
        k = min(chunk, resamples - done)
        idx = rng.integers(0, m, size=(k, m))
        for n, arr in arrs.items():
            sa = arr[:, 0][idx].sum(axis=1)
            sc = arr[:, 1][idx].sum(axis=1)
            draws[n][done:done + k] = 100.0 * (sa - sc) / sa
        done += k
    return draws, m


def q(d, level=0.995, k=1):
    a = (1 - level) / (2 * k)
    lo, hi = np.quantile(d, [a, 1 - a], method="linear")
    return [float(lo), float(hi)]


# 1. reproduction
draws, m = boot(conf, 20261113)
rep = {}
reported = {r["comparison"]: r for r in csv.DictReader(open(
    Path(__file__).resolve().parents[3] / "results" / "20261114_050438_SVGX-2026-11-A" / "10_tables" / "confirmation_main_comparisons.csv",
    encoding="utf-8"))}
for n in CONTRASTS:
    mg, bf = q(draws[n]), q(draws[n], k=3)
    rr = reported[n]
    rep[n] = {"marginal_995": mg, "bonferroni_k3": bf,
              "reported_marginal": [float(rr["ci995_low"]), float(rr["ci995_high"])],
              "reported_bonferroni": [float(rr["bonf_low"]), float(rr["bonf_high"])],
              "matches_report_4dp": all(abs(round(x, 4) - y) < 1e-9 for x, y in zip(mg + bf, [float(rr["ci995_low"]), float(rr["ci995_high"]), float(rr["bonf_low"]), float(rr["bonf_high"])])),
              "draws_below_bonf_low": int((draws[n] < bf[0]).sum()), "draws_above_bonf_high": int((draws[n] > bf[1]).sum()),
              "share_of_draws_le_0": float((draws[n] <= 0).mean()), "share_of_draws_ge_1pct": float((draws[n] >= 1.0).mean())}
out["A09_reproduction"] = {"families": m, "resamples": 50000, "seed": 20261113, "contrasts": rep}

# 2. post-hoc sensitivity
seeds = list(range(1, 21))
spread = {n: {"bonf_low": [], "bonf_high": []} for n in ("G_vs_brotli11", "G_vs_Cstar", "G_vs_U")}
for s in seeds:
    d2, _ = boot(conf, s)
    for n in spread:
        lo, hi = q(d2[n], k=3)
        spread[n]["bonf_low"].append(lo)
        spread[n]["bonf_high"].append(hi)
out["A09_posthoc_seed_sensitivity"] = {n: {k: {"min": min(v), "max": max(v), "sd": statistics.pstdev(v)} for k, v in d.items()}
                                       for n, d in spread.items()}
fd, nf = boot(conf, 20261113, unit="file")
out["A09_posthoc_file_level_bootstrap_NOT_valid_for_inference"] = {
    "files": nf, **{n: {"bonferroni_k3": q(fd[n], k=3)} for n in ("G_vs_brotli11", "G_vs_Cstar", "G_vs_U")},
    "note": "ignores within-family dependence; shown only to quantify the effect of clustering"}

# 3. concentration (G vs Brotli, confirmation)
fam = defaultdict(lambda: {"files": 0, "B": 0, "C_G": 0, "structured": 0, "category": set()})
for r in conf:
    f = fam[r["family"]]
    f["files"] += 1
    f["B"] += r["B"]
    f["C_G"] += r["C_G"]
    f["structured"] += r["branch_G"] == "structured"
    f["category"].add(r["category"])
tot_gain = sum(f["B"] - f["C_G"] for f in fam.values())
tot_B = sum(f["B"] for f in fam.values())
ranked = sorted(fam.items(), key=lambda kv: -(kv[1]["B"] - kv[1]["C_G"]))
fam_table = []
for fid, f in ranked:
    g = f["B"] - f["C_G"]
    fam_table.append({"family": fid, "categories": "+".join(sorted(f["category"])), "files": f["files"],
                      "structured_files": f["structured"], "B": f["B"], "C_G": f["C_G"], "gain_bytes": g,
                      "gain_percent_within_family": 100.0 * g / f["B"], "share_of_total_gain": g / tot_gain,
                      "share_of_total_B": f["B"] / tot_B})
with open(D / "family_contributions_confirmation.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(fam_table[0].keys()))
    w.writeheader()
    w.writerows(fam_table)
files_ranked = sorted(conf, key=lambda r: -(r["B"] - r["C_G"]))
file_gain_total = sum(r["B"] - r["C_G"] for r in conf)


def gain_without(fids):
    rs = [r for r in conf if r["family"] not in fids]
    sb = sum(r["B"] for r in rs)
    return 100.0 * (sb - sum(r["C_G"] for r in rs)) / sb


lofo = {fid: gain_without({fid}) for fid in fam}
out["A11_concentration"] = {
    "pooled_gain_percent": 100.0 * tot_gain / tot_B, "total_gain_bytes": tot_gain,
    "families_with_positive_gain": sum(1 for _, f in ranked if f["B"] > f["C_G"]), "families": len(fam),
    "top_family_share": [{"k": k, "share": sum(x["share_of_total_gain"] for x in fam_table[:k]),
                          "families": [x["family"] for x in fam_table[:k]]} for k in (1, 3, 5)],
    "top_file_share": [{"k": k, "share": sum(r["B"] - r["C_G"] for r in files_ranked[:k]) / file_gain_total} for k in (1, 3, 5, 10)],
    "leave_one_family_out": {"min": min(lofo.values()), "max": max(lofo.values()),
                             "argmin": min(lofo, key=lofo.get), "argmax": max(lofo, key=lofo.get)},
    "leave_top_k_families_out": {k: gain_without({x["family"] for x in fam_table[:k]}) for k in (1, 3, 5)},
    "equal_family_mean_gain_percent": statistics.mean(x["gain_percent_within_family"] for x in fam_table),
    "file_median_gain_percent": statistics.median(100.0 * (r["B"] - r["C_G"]) / r["B"] for r in conf),
    "file_median_gain_percent_structured_only": statistics.median(
        100.0 * (r["B"] - r["C_G"]) / r["B"] for r in conf if r["branch_G"] == "structured"),
}
cat = {}
for c in sorted({r["category"] for r in conf}):
    rs = [r for r in conf if r["category"] == c]
    sb = sum(r["B"] for r in rs)
    cat[c] = {"files": len(rs), "families": len({r["family"] for r in rs}), "structured_G": sum(r["branch_G"] == "structured" for r in rs),
              "gain_percent_vs_brotli": 100.0 * (sb - sum(r["C_G"] for r in rs)) / sb,
              "ceiling_percent": 100.0 * (sb - sum(r["O"] for r in rs)) / sb}
out["A11_by_category"] = cat
brackets = [(0, 4096), (4096, 65536), (65536, 1048576), (1048576, 10 ** 12)]
sz = {}
for lo, hi in brackets:
    rs = [r for r in conf if lo <= r["orig_len"] < hi]
    if rs:
        sb = sum(r["B"] for r in rs)
        sz[f"[{lo},{hi})"] = {"files": len(rs), "structured_G": sum(r["branch_G"] == "structured" for r in rs),
                              "gain_percent_vs_brotli": 100.0 * (sb - sum(r["C_G"] for r in rs)) / sb}
out["A11_by_size_bracket"] = sz

# 4. mechanism decomposition (confirmation)
sB = sum(r["B"] for r in conf)
sO = sum(r["O"] for r in conf)
dec = {"sum_B": sB, "sum_O": sO, "ceiling_gain_bytes": sB - sO}
for p in ("D", "P", "I", "U", "G"):
    sc = sum(r[f"C_{p}"] for r in conf)
    dec[p] = {"sum_C": sc, "gain_vs_brotli_bytes": sB - sc, "gain_vs_brotli_percent": 100.0 * (sB - sc) / sB,
              "remaining_gap_to_ceiling_bytes": sc - sO,
              "share_of_ceiling_gain_realised": (sB - sc) / (sB - sO)}
dec["G_closes_share_of_D_gap"] = 1 - dec["G"]["remaining_gap_to_ceiling_bytes"] / dec["D"]["remaining_gap_to_ceiling_bytes"]
dec["xwrt_vs_brotli_pooled_percent"] = None
xw = [r for r in conf if r["E_xwrt_l6"] != ""]
sx = sum(int(r["E_xwrt_l6"]) for r in xw)
sbx = sum(r["B"] for r in xw)
dec["xwrt_vs_brotli_pooled_percent"] = 100.0 * (sbx - sx) / sbx
dec["xwrt_vs_brotli_file_wins_W_T_L"] = [sum(int(r["E_xwrt_l6"]) < r["B"] for r in xw), sum(int(r["E_xwrt_l6"]) == r["B"] for r in xw),
                                         sum(int(r["E_xwrt_l6"]) > r["B"] for r in xw)]
out["A07_decomposition"] = dec
# G vs U losses detail
out["A10_G_vs_U_losses"] = [{"file_id": r["file_id"], "family": r["family"], "C_U": r["C_U"], "C_G": r["C_G"],
                             "branch_U": r["branch_U"], "branch_G": r["branch_G"]} for r in conf if r["C_G"] > r["C_U"]]
(D / "a03_results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))

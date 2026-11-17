"""REV1 analysis (docs/PROTOCOL_REV1.md §5–§7). Pure computation over the B1/B2/B3 result files.

Confirmatory family {R1 (B1), Gain_H (B2), tau_dec (B3)}: family-cluster percentile bootstrap, 50 000 resamples,
numpy PCG64 (seed in config/rev1.toml), quantile method "linear", Bonferroni k = 3 at family coverage 99.5 %
(tails 0.005/6). BCa (jackknife acceleration over families) is reported as a sensitivity analysis.
Every estimand is a ratio of sums of per-file quantities; it is computed twice (from the result rows and from the
per-file CSV written here) and asserted equal. Invariants of §3 are asserted per file.
Pre-specified wording (§7) is applied mechanically to the Bonferroni bounds.

usage: python rev1/analysis.py pilot|confirmation [--resamples N]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tomllib
from collections import OrderedDict
from statistics import NormalDist

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
from common import OUT, REV1, ledger_size_results, manifest, read_jsonl, write_json  # noqa: E402

CFG = tomllib.loads((REV1 / "config" / "rev1.toml").read_text(encoding="utf-8"))
ND = NormalDist()


# ----------------------------------------------------------------------------- estimands as ratios of sums
# An estimand is (numerator terms, denominator terms); each term is (coefficient, column). Value = num / den.
B1_EST = OrderedDict([
    ("R1", ([(1, "C_D0"), (-1, "C_F")], [(1, "B"), (-1, "C_F")])),
    ("R11", ([(1, "C_M010"), (-1, "C_F")], [(1, "B"), (-1, "C_F")])),
    ("pi_B_D0", ([(1, "B"), (-1, "C_D0")], [(1, "B")])),
    ("pi_D0_M01", ([(1, "C_D0"), (-1, "C_M01")], [(1, "B")])),
    ("pi_M01_M010", ([(1, "C_M01"), (-1, "C_M010")], [(1, "B")])),
    ("pi_M010_F", ([(1, "C_M010"), (-1, "C_F")], [(1, "B")])),
    ("gain_F_vs_B", ([(1, "B"), (-1, "C_F")], [(1, "B")])),
    ("gain_F_vs_T", ([(1, "C_T"), (-1, "C_F")], [(1, "C_T")])),
    ("gain_F_vs_Z", ([(1, "C_Z"), (-1, "C_F")], [(1, "C_Z")])),
    ("gain_T_vs_B", ([(1, "B"), (-1, "C_T")], [(1, "B")])),
    ("gain_Z_vs_B", ([(1, "B"), (-1, "C_Z")], [(1, "B")])),
])
B2_EST = OrderedDict([
    ("Gain_H", ([(1, "P"), (-1, "H")], [(1, "P")])),
    ("gain_G_vs_P", ([(1, "P"), (-1, "C_G")], [(1, "P")])),
    ("gain_G_vs_ZD", ([(1, "ZD"), (-1, "C_G")], [(1, "ZD")])),
    ("gain_G_vs_ZD_amortised", ([(1, "ZD_am"), (-1, "C_G")], [(1, "ZD_am")])),
    ("gain_G_vs_BA", ([(1, "BA"), (-1, "C_G")], [(1, "BA")])),
    ("gain_G_vs_BL", ([(1, "BL"), (-1, "C_G")], [(1, "BL")])),
    ("gain_P_vs_B", ([(1, "B"), (-1, "P")], [(1, "B")])),
])
B3_EST = OrderedDict([
    ("tau_dec", ([(1, "dec_S")], [(1, "rawdec_S")])),
    ("tau_enc", ([(1, "enc_S")], [(1, "rawenc_S")])),
    ("tau_dec_rawgroup", ([(1, "dec_R")], [(1, "rawdec_R")])),
    ("tau_enc_rawgroup", ([(1, "enc_R")], [(1, "rawenc_R")])),
])
CONFIRMATORY = {"R1": "B1", "Gain_H": "B2", "tau_dec": "B3"}


def value(rows, est) -> float:
    num, den = est
    n = sum(c * sum(float(r[k]) for r in rows) for c, k in num)
    d = sum(c * sum(float(r[k]) for r in rows) for c, k in den)
    return n / d if d else float("nan")


def fam_matrix(rows, cols):
    fams = OrderedDict()
    for r in sorted(rows, key=lambda r: (r["family"], r["file_id"])):
        fams.setdefault(r["family"], []).append(r)
    M = np.array([[sum(float(r[c]) for r in rs) for c in cols] for rs in fams.values()], dtype=np.float64)
    return list(fams), M


def boot(rows, ests: dict, resamples: int, seed: int) -> dict:
    cols = sorted({k for e in ests.values() for part in e for _, k in part})
    ci = {c: i for i, c in enumerate(cols)}
    fams, M = fam_matrix(rows, cols)
    m = len(fams)
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = {n: np.empty(resamples) for n in ests}
    done = 0
    while done < resamples:
        k = min(2000, resamples - done)
        idx = rng.integers(0, m, size=(k, m))
        S = M[idx].sum(axis=1)                      # (k, cols)
        for n, (num, den) in ests.items():
            nv = sum(c * S[:, ci[col]] for c, col in num)
            dv = sum(c * S[:, ci[col]] for c, col in den)
            with np.errstate(divide="ignore", invalid="ignore"):
                draws[n][done:done + k] = np.where(dv != 0, nv / dv, np.nan)
        done += k
    # leave-one-family-out jackknife for BCa
    tot = M.sum(axis=0)
    jack = {}
    for n, (num, den) in ests.items():
        vals = []
        for j in range(m):
            S = tot - M[j]
            nv = sum(c * S[ci[col]] for c, col in num)
            dv = sum(c * S[ci[col]] for c, col in den)
            vals.append(nv / dv if dv else float("nan"))
        jack[n] = np.array(vals)
    return {"m": m, "draws": draws, "jack": jack}


def intervals(theta: float, draws: np.ndarray, jack: np.ndarray, k: int, coverage: float) -> dict:
    alpha = 1 - coverage
    f = draws[np.isfinite(draws)]
    pm = [alpha / 2, 1 - alpha / 2]
    pb = [alpha / (2 * k), 1 - alpha / (2 * k)]
    res = {"undefined_draws": int((~np.isfinite(draws)).sum()),
           "marginal": [float(x) for x in np.quantile(f, pm, method="linear")],
           "bonferroni": [float(x) for x in np.quantile(f, pb, method="linear")], "probs_bonferroni": pb}
    # BCa (sensitivity)
    prop = (np.sum(f < theta) + 0.5 * np.sum(f == theta)) / f.size
    prop = min(max(prop, 1 / (f.size + 1)), f.size / (f.size + 1))
    z0 = ND.inv_cdf(prop)
    jf = jack[np.isfinite(jack)]
    d = jf.mean() - jf
    den = 6 * (np.sum(d ** 2) ** 1.5)
    acc = float(np.sum(d ** 3) / den) if den > 0 else 0.0

    def adj(p):
        z = ND.inv_cdf(p)
        return ND.cdf(z0 + (z0 + z) / (1 - acc * (z0 + z)))
    res["bca_bonferroni"] = [float(x) for x in np.quantile(f, [adj(p) for p in pb], method="linear")]
    res["bca_z0"], res["bca_acceleration"] = z0, acc
    return res


# ----------------------------------------------------------------------------- row preparation and invariants
def b1_rows(split):
    rows = read_jsonl(OUT / "b1" / f"b1_{split}.jsonl")
    if not rows:
        return None
    for r in rows:
        assert not r["defects"], f"B1 defect in {r['file_id']}: {r['defects']}"
        chain = [r["B"], r["C_D0"], r["C_M01"], r["C_M010"], r["C_F"]]
        assert all(a >= b for a, b in zip(chain, chain[1:])), f"B1 monotonicity violated {r['file_id']} {chain}"
        assert r["C_F"] == r["C_F_ledger"], "B1 F differs from the ledger"
        for k in ("T", "Z"):
            assert r[f"C_{k}"] <= r["B"]
    return rows


def b2_rows(split, n_files):
    rows = read_jsonl(OUT / "b2" / f"b2_{split}.jsonl")
    if not rows:
        return None
    dlen = json.loads((REV1 / "config" / "zstd_pilot_dict.json").read_text(encoding="utf-8"))["dict_len"]
    for r in rows:
        assert not r["defects"], f"B2 defect in {r['file_id']}: {r['defects']}"
        assert r["H"] <= r["P"], "invariant H <= P"
        if r["eligible"]:
            assert r["H"] == min(r["P"], r["S_P"])
        r["ZD_am"] = r["ZD"] + dlen / n_files
    return rows


def b3_rows(split):
    rows = read_jsonl(OUT / "b3" / f"b3_{split}.jsonl")
    if not rows:
        return None
    for r in rows:
        assert not r["defects"], f"B3 defect in {r['file_id']}"
        g = r["group"]
        for k, src in (("dec", "decode_median_ns"), ("enc", "encode_median_ns"),
                       ("rawdec", "raw_decode_median_ns"), ("rawenc", "raw_encode_median_ns")):
            r[f"{k}_S"] = r[src] if g == "S" else 0
            r[f"{k}_R"] = r[src] if g == "R" else 0
    return rows


def write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def wording(name, lo, hi, est):
    if name == "R1":
        if lo >= 0.5:
            return "prediction is the main source of the saving"
        if lo >= 0.25:
            return "prediction contributes a substantial share"
        if est >= 0.10:
            return "prediction contributes a minor share (alternative title, §7)"
        return "the saving comes mainly from stream separation and integer re-coding (alternative title, §7)"
    if name == "Gain_H":
        return ("geometric modelling retains value over a context-mixing back end" if lo >= 0.005
                else "no material gain over a strong back end")
    if name == "tau_dec":
        if hi < 1:
            return "faster"
        if lo > 1:
            return f"slower by {est:.2f}x"
        return "comparable"
    return None


def analyse(split: str, resamples: int) -> dict:
    seed = int(CFG["statistics"]["bootstrap_seed"])
    cov = float(CFG["statistics"]["family_coverage"])
    k = int(CFG["statistics"]["bonferroni_k"])
    man = manifest(split)
    n_files = len(man)
    excl = set()
    with open(REV1 / "config" / "license_sensitivity_exclude.csv", encoding="utf-8", newline="") as f:
        excl = {r["file_id"] for r in csv.DictReader(f)}
    adir = OUT / "analysis" / split
    out = {"split": split, "resamples": resamples, "seed": seed, "coverage": cov, "bonferroni_k": k, "experiments": {}}
    led = ledger_size_results({r["file_id"] for r in man})
    for exp, rows, ests, cols in (
            ("B1", b1_rows(split), B1_EST, ["file_id", "family", "category", "B", "C_F", "C_D0", "C_M01", "C_M010", "C_T", "C_Z"]),
            ("B2", b2_rows(split, n_files), B2_EST, ["file_id", "family", "category", "B", "C_G", "P", "H", "ZD", "ZD_am", "BA", "BL"]),
            ("B3", b3_rows(split), B3_EST, ["file_id", "family", "category", "group", "dec_S", "rawdec_S", "enc_S", "rawenc_S",
                                            "dec_R", "rawdec_R", "enc_R", "rawenc_R"])):
        if rows is None:
            out["experiments"][exp] = {"available": False}
            continue
        if exp in ("B1", "B2"):
            assert {r["file_id"] for r in rows} == {r["file_id"] for r in man}, f"{exp}: incomplete split"
            # two-way: B and C_G/C_F straight from the frozen ledger
            colF = "C_F" if exp == "B1" else "C_G"
            assert sum(r["B"] for r in rows) == sum(led[r["file_id"]]["B"] for r in rows)
            assert sum(r[colF] for r in rows) == sum(led[r["file_id"]]["profiles"]["G"]["C"] for r in rows)
        csv_rows = write_csv(adir / f"per_file_{exp}.csv", rows, cols)
        bs = boot(rows, ests, resamples, seed)
        res = {"available": True, "files": len(rows), "families": bs["m"], "estimands": {}}
        for name, e in ests.items():
            v1, v2 = value(rows, e), value(csv_rows, e)
            assert math.isclose(v1, v2, rel_tol=0, abs_tol=1e-12), f"two-way mismatch {name}: {v1} vs {v2}"
            iv = intervals(v1, bs["draws"][name], bs["jack"][name], k, cov)
            entry = {"estimate": v1, **iv}
            if exp != "B3":
                kept = [r for r in rows if r["file_id"] not in excl]
                entry["licence_sensitivity_estimate"] = value(kept, e) if len(kept) < len(rows) else None
            if name in CONFIRMATORY:
                lo, hi = iv["bonferroni"]
                entry["confirmatory"] = True
                entry["wording"] = wording(name, lo, hi, v1)
            res["estimands"][name] = entry
        if exp == "B1":
            el = [r for r in rows if r["eligible"]]
            res["diagnostics"] = {"eligible_files": len(el), "holes": sum(r["hole_count"] for r in el)}
            for a in ("D0", "M01", "M010", "F"):
                res["diagnostics"][f"geometry_bits_per_hole_{a}"] = sum(r[f"geometry_bits_{a}"] for r in el) / max(1, sum(r["hole_count"] for r in el))
            res["diagnostics"]["Z_bits_per_hole"] = sum(r["Z_bits"] for r in el) / max(1, sum(r["hole_count"] for r in el))
            res["diagnostics"]["sum_S"] = {a: sum(r[f"S_{a}"] for r in el) for a in ("D0", "M01", "M010", "F", "T", "Z")}
            res["sums"] = {c: sum(r[c] for r in rows) for c in ("B", "C_D0", "C_M01", "C_M010", "C_F", "C_T", "C_Z")}
            assert 0 <= res["estimands"]["R1"]["estimate"] <= 1
        if exp == "B2":
            res["sums"] = {c: sum(r[c] for r in rows) for c in ("B", "C_G", "P", "H", "ZD", "BA", "BL")}
            res["hybrid_files"] = sum(r["H_branch"] == "hybrid" for r in rows)
            assert res["sums"]["H"] <= res["sums"]["P"]
        if exp == "B3":
            S = [r for r in rows if r["group"] == "S"]
            res["throughput_MiB_s"] = {
                k2: sum(r["size"] for r in S) / (2 ** 20 * sum(r[src] for r in S) / 1e9)
                for k2, src in (("G_encode", "encode_median_ns"), ("G_decode", "decode_median_ns"),
                                ("raw_encode", "raw_encode_median_ns"), ("raw_decode", "raw_decode_median_ns"))}
            res["within_file_iqr_over_median_median"] = float(np.median([r["decode_iqr_ns"] / r["decode_median_ns"] for r in rows]))
        out["experiments"][exp] = res
    write_json(adir / "estimands.json", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["pilot", "confirmation"])
    ap.add_argument("--resamples", type=int, default=int(CFG["statistics"]["bootstrap_resamples"]))
    a = ap.parse_args()
    res = analyse(a.split, a.resamples)
    for exp, r in res["experiments"].items():
        if not r.get("available"):
            print(f"[{exp}] not available")
            continue
        print(f"[{exp}] files {r['files']}, families {r['families']}")
        for n, e in r["estimands"].items():
            tag = " (confirmatory)" if e.get("confirmatory") else ""
            print(f"   {n}{tag}: {e['estimate']:.5f}  Bonf [{e['bonferroni'][0]:.5f}, {e['bonferroni'][1]:.5f}]  "
                  f"BCa [{e['bca_bonferroni'][0]:.5f}, {e['bca_bonferroni'][1]:.5f}]" + (f"  -> {e['wording']}" if e.get("wording") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

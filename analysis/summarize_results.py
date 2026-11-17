"""Recompute the reported SVGX results from the saved measurements of run 20261114_050438_SVGX-2026-11-A.

Inputs are opened read-only:
  <run>/ledger.sqlite                       (sqlite URI mode=ro&immutable=1)
  <run>/02_corpus/{pilot,confirmation}.csv  (corpus manifests)
  <run>/10_tables/*_main_comparisons.csv    (original report tables, cross-check only)
  <run>/07_statistics/confirmation_statistics.json (bootstrap intervals, reported as computed by the run)
  <run>/01_protocol/{environment,freeze}.json
No codec is executed and nothing under <run> is written.

Outputs (in <out_dir>):
  numbers.json                  every summary value reported in README.md
  figure_data/*.csv             the exact data behind Figs. 3-5
  tables/main_comparisons_<split>.csv  comparison table regenerated from the ledger
The script also checks the regenerated comparisons field by field against the run's own 10_tables/*.csv.
Usage: python -I analysis/summarize_results.py results/20261114_050438_SVGX-2026-11-A analysis/output
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
import sqlite3

ARMS = ["D", "P", "I", "U", "G"]
COMPARATORS = ["xwrt_l6", "xz9e", "ppmd7z", "zstd19", "gzip9"]
SPLITS = ["pilot", "confirmation"]
BRACKETS = [(0, 4096, "<4 KiB"), (4096, 65536, "4-64 KiB"), (65536, 1048576, "64 KiB-1 MiB"), (1048576, 1 << 62, ">=1 MiB")]


def ro_connect(p: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:" + str(p).replace("\\", "/") + "?mode=ro&immutable=1", uri=True)


def gain(a: int, c: int) -> float:
    return 100.0 * (a - c) / a


def load(run: Path):
    corpus = {}
    for s in SPLITS:
        with open(run / "02_corpus" / f"{s}.csv", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                corpus[r["file_id"]] = dict(r, split=s)
    con = ro_connect(run / "ledger.sqlite")
    svgx, comp, brotli_job = {}, defaultdict(dict), {}
    for key, method, task, payload, status, result in con.execute(
            "select key, method, task, payload, status, result from jobs where task='size'"):
        assert status == "done", key
        fid = json.loads(payload)["file_id"]
        res = json.loads(result)
        if method == "svgx":
            svgx[fid] = res
        elif method == "brotli11":
            brotli_job[fid] = res
        else:
            comp[fid][method] = res
    timing = defaultdict(lambda: defaultdict(list))
    for key, method, result in con.execute("select key, method, result from jobs where task='timing'"):
        split, sha, build, m, rep, task = key.split("|")
        res = json.loads(result)
        timing[(split, sha)][method].append((int(rep), res))
    events = con.execute("select count(*) from attempts where status != 'done'").fetchone()[0]
    con.close()
    return corpus, svgx, comp, brotli_job, timing, events


def per_file_rows(corpus, svgx, comp, brotli_job):
    rows = []
    for fid, res in svgx.items():
        c = corpus[fid]
        st = res.get("stats") or {}
        prof = res["profiles"]
        row = {"file_id": fid, "split": c["split"], "category": c["category"], "family": c["family"],
               "orig_len": int(c["size"]), "B": res["B"], "eligible": bool(st.get("eligible")),
               "blocks": st.get("blocks") or 0, "file_reason": st.get("file_reason"),
               "brotli_job_len": brotli_job[fid]["len"], "brotli_job_ok": brotli_job[fid]["roundtrip_ok"],
               "codec_raw_equals_baseline": res.get("codec_raw_equals_baseline"),
               "common_sections_equal": res.get("common_sections_equal"), "escape_equal_IUG": res.get("escape_equal_IUG")}
        restored_all = True
        for a in ARMS:
            p = prof[a]
            inv = p["invariants"]
            row[f"C_{a}"] = p["C"]
            row[f"branch_{a}"] = inv["branch"]
            row[f"F_{a}"] = inv.get("forced_len")
            row["O"] = inv["O"]
            fs = p.get("forced_sections") or {}
            for sec in ("literals", "schedule", "geometry", "spelling", "escapes"):
                row[f"{sec}_{a}"] = (fs.get(sec) or {}).get("len")
            for vk in ("verify_final", "verify_forced"):
                v = p.get(vk)
                if v is None:
                    continue
                ok = v["native_ok"] and v["reference_ok"] and v["native_sha256"] == v["reference_sha256"] \
                    and v["native_sha256"] == c["sha256"]
                restored_all &= ok
            assert inv["C_le_B"] and inv["O_le_C"] and inv["ok"], fid
        row["restored_both_decoders_all_arms"] = restored_all
        for m in COMPARATORS:
            row[f"E_{m}"] = comp[fid][m]["len"]
            row[f"rt_{m}"] = comp[fid][m]["roundtrip_ok"]
        row["stats"] = st
        rows.append(row)
    return rows


def compare(rows, colA, colC="C_G"):
    sa = sum(r[colA] for r in rows)
    sc = sum(r[colC] for r in rows)
    fw = sum(r[colA] > r[colC] for r in rows)
    fl = sum(r[colA] < r[colC] for r in rows)
    fam = defaultdict(int)
    for r in rows:
        fam[r["family"]] += r[colA] - r[colC]
    med = statistics.median(100.0 * (r[colA] - r[colC]) / r[colA] for r in rows)
    return {"sum_A": sa, "sum_C": sc, "saved_bytes": sa - sc, "gain_percent": gain(sa, sc),
            "file_wins": fw, "file_ties": len(rows) - fw - fl, "file_losses": fl,
            "family_wins": sum(v > 0 for v in fam.values()), "family_ties": sum(v == 0 for v in fam.values()),
            "family_losses": sum(v < 0 for v in fam.values()), "families": len(fam), "file_median_gain_percent": med}


def split_summary(rows, split):
    R = [r for r in rows if r["split"] == split]
    out = {"files": len(R), "families": len({r["family"] for r in R}), "orig_bytes": sum(r["orig_len"] for r in R)}
    out["per_category"] = {cat: {"files": sum(r["category"] == cat for r in R),
                                 "families": len({r["family"] for r in R if r["category"] == cat}),
                                 "orig_bytes": sum(r["orig_len"] for r in R if r["category"] == cat)}
                           for cat in ("maps", "illustrations", "diagrams", "icons")}
    out["sum_B"] = sum(r["B"] for r in R)
    out["sum_O"] = sum(r["O"] for r in R)
    out["ceiling_gain_percent"] = gain(out["sum_B"], out["sum_O"])
    for a in ARMS:
        out[f"sum_C_{a}"] = sum(r[f"C_{a}"] for r in R)
        out[f"structured_{a}"] = sum(r[f"branch_{a}"] == "structured" for r in R)
        out[f"ceiling_realised_{a}"] = (out["sum_B"] - out[f"sum_C_{a}"]) / (out["sum_B"] - out["sum_O"])
        out[f"above_ceiling_bytes_{a}"] = out[f"sum_C_{a}"] - out["sum_O"]
    for m in COMPARATORS:
        out[f"sum_{m}"] = sum(r[f"E_{m}"] for r in R)
    out["eligible_files"] = sum(r["eligible"] for r in R)
    out["files_with_forced_stream"] = sum(r["F_G"] is not None for r in R)
    gg = gl = 0
    for r in R:
        if r["F_G"] is not None:
            gg += max(r["B"] - r["F_G"], 0)
            gl += max(r["F_G"] - r["B"], 0)
    out["forced_gross_gain_G"], out["forced_gross_loss_G"] = gg, gl
    out["forced_net_G_if_always_structured"] = gg - gl
    # comparisons
    comps = {"G_vs_Cstar(P)": compare(R, "C_P"), "G_vs_U": compare(R, "C_U"), "G_vs_brotli11": compare(R, "B"),
             "G_vs_I": compare(R, "C_I"), "G_vs_D": compare(R, "C_D"), "G_vs_P": compare(R, "C_P")}
    for m in COMPARATORS:
        comps[f"G_vs_{m}"] = compare(R, f"E_{m}")
    for a in ("D", "P", "I", "U"):
        comps[f"{a}_vs_brotli11"] = compare(R, "B", f"C_{a}")
    comps["xwrt_l6_vs_brotli11"] = compare(R, "B", "E_xwrt_l6")
    out["comparisons"] = comps
    # decomposition (exact byte totals)
    sB, sO = out["sum_B"], out["sum_O"]
    steps = [("Brotli-11 -> G", sB, out["sum_C_G"]), ("Brotli-11 -> O (free spelling)", sB, sO),
             ("Brotli-11 -> D", sB, out["sum_C_D"]), ("D -> G", out["sum_C_D"], out["sum_C_G"]),
             ("D -> I", out["sum_C_D"], out["sum_C_I"]), ("I -> U", out["sum_C_I"], out["sum_C_U"]),
             ("U -> G", out["sum_C_U"], out["sum_C_G"]), ("D -> P", out["sum_C_D"], out["sum_C_P"])]
    out["decomposition"] = [{"step": s, "saved_bytes": a - c, "percent_of_sum_B": 100.0 * (a - c) / sB} for s, a, c in steps]
    # stratification
    out["by_category"] = {}
    for cat in ("illustrations", "maps", "diagrams", "icons"):
        S = [r for r in R if r["category"] == cat]
        b, cg, o = sum(r["B"] for r in S), sum(r["C_G"] for r in S), sum(r["O"] for r in S)
        out["by_category"][cat] = {"files": len(S), "families": len({r["family"] for r in S}),
                                   "structured_G": sum(r["branch_G"] == "structured" for r in S),
                                   "eligible": sum(r["eligible"] for r in S),
                                   "gain_percent": gain(b, cg), "ceiling_percent": gain(b, o), "sum_B": b}
    out["by_size"] = {}
    for lo, hi, lab in BRACKETS:
        S = [r for r in R if lo <= r["orig_len"] < hi]
        b, cg = sum(r["B"] for r in S), sum(r["C_G"] for r in S)
        out["by_size"][lab] = {"files": len(S), "structured_G": sum(r["branch_G"] == "structured" for r in S),
                               "eligible": sum(r["eligible"] for r in S), "gain_percent": gain(b, cg) if b else None}
    # concentration
    fam = defaultdict(int)
    for r in R:
        fam[r["family"]] += r["B"] - r["C_G"]
    tot = sum(fam.values())
    fs = sorted(fam.values(), reverse=True)
    files_s = sorted((r["B"] - r["C_G"] for r in R), reverse=True)
    out["concentration"] = {
        "families_positive": sum(v > 0 for v in fam.values()), "total_saved": tot,
        "family_share_top": {k: sum(fs[:k]) / tot for k in (1, 3, 5)},
        "file_share_top": {k: sum(files_s[:k]) / tot for k in (1, 3, 5, 10)}}
    order = sorted(fam, key=lambda f: -fam[f])
    lto = {}
    for k in (1, 3, 5):
        drop = set(order[:k])
        S = [r for r in R if r["family"] not in drop]
        lto[k] = gain(sum(r["B"] for r in S), sum(r["C_G"] for r in S))
    out["concentration"]["leave_top_k_families_out_gain_percent"] = lto
    lofo = []
    for f in fam:
        S = [r for r in R if r["family"] != f]
        lofo.append(gain(sum(r["B"] for r in S), sum(r["C_G"] for r in S)))
    out["concentration"]["leave_one_family_out_range"] = [min(lofo), max(lofo)]
    eq = []
    for f in fam:
        S = [r for r in R if r["family"] == f]
        eq.append(gain(sum(r["B"] for r in S), sum(r["C_G"] for r in S)))
    out["concentration"]["equal_family_mean_gain_percent"] = sum(eq) / len(eq)
    struct = [r for r in R if r["branch_G"] == "structured"]
    out["structured_files_G"] = {
        "files": len(struct), "sum_B": sum(r["B"] for r in struct), "sum_C_G": sum(r["C_G"] for r in struct),
        "gain_percent": gain(sum(r["B"] for r in struct), sum(r["C_G"] for r in struct)),
        "median_file_gain_percent": statistics.median(100.0 * (r["B"] - r["C_G"]) / r["B"] for r in struct),
        "orig_len_min": min(r["orig_len"] for r in struct), "orig_len_median": statistics.median(r["orig_len"] for r in struct),
        "sections_G": {sec: sum(r[f"{sec}_G"] for r in struct) for sec in ("literals", "schedule", "geometry", "spelling", "escapes")},
        "header_bytes": 60 * len(struct)}
    # geometry and spelling statistics from the codec's own per-file stats (eligible files)
    E = [r for r in R if r["eligible"]]
    modes = [0, 0, 0, 0]
    blocks = holes = gbits = rbits = hbits = cand = 0
    for r in E:
        cm = r["stats"]["common"]
        for i, v in enumerate(cm["mode_counts"]):
            modes[i] += v
        blocks += r["stats"]["blocks"]
        holes += cm["hole_count"]
        gbits += cm["geometry_bits"]
        rbits += cm["geometry_residual_bits"]
        hbits += cm["geometry_header_bits"]
        cand += cm["ref_candidates_evaluated"]
    out["geometry_eligible"] = {"files": len(E), "blocks": blocks, "holes": holes, "mode_counts_00_01_10_11": modes,
                                "mode_share": [m / blocks for m in modes], "geometry_bits": gbits,
                                "residual_bits": rbits, "block_header_bits": hbits,
                                "bits_per_hole": gbits / holes, "residual_bits_per_hole": rbits / holes,
                                "ref_candidates_evaluated": cand}
    tokens = multi = esc = 0
    hits = [0] * 8
    ib = {"I": 0.0, "U": 0.0, "G": 0.0}
    spell_bits = {a: 0 for a in ARMS}
    esc_count = {a: 0 for a in ARMS}
    distinct_hist = Counter()
    for r in E:
        for ro in r["stats"]["roles"]:
            tokens += ro["tokens"]
            multi += ro["multi_match"]
            esc += ro["escapes_rules"]
            for i, h in enumerate(ro["rule_hits"]):
                hits[i] += h
            for a in ("I", "U", "G"):
                ib[a] += ro[f"ideal_bits_{a}"]
        for a in ARMS:
            spell_bits[a] += r["stats"]["profiles"][a]["spelling_bits"]
            esc_count[a] += r["stats"]["profiles"][a]["escape_count"]
    out["spelling_eligible"] = {"tokens": tokens, "multi_rule_matches": multi, "rule_escapes": esc,
                                "rule_hits_1_to_8": hits, "rule_hit_share": [h / tokens for h in hits],
                                "ideal_bits": ib, "ideal_bits_per_token": {a: v / tokens for a, v in ib.items()},
                                "spelling_bits": spell_bits, "escape_count": esc_count,
                                "spelling_bits_per_token": {a: spell_bits[a] / tokens for a in ARMS}}
    pr = Counter()
    fr = Counter()
    for r in R:
        for k, v in (r["stats"].get("path_reasons") or {}).items():
            pr[k] += v
        if not r["eligible"]:
            fr[r["file_reason"] or "none"] += 1
    out["path_reasons"] = dict(pr)
    out["ineligible_file_reasons"] = dict(fr)
    out["svg_path_candidates"] = sum(r["stats"].get("svg_path_candidates") or 0 for r in R)
    out["modeled_paths"] = sum(r["stats"].get("modeled_paths") or 0 for r in R)
    return out, R


def timing_summary(timing, corpus_by_sha):
    per = defaultdict(dict)
    for (split, sha), methods in timing.items():
        for m, reps in methods.items():
            meas = [res for rep, res in reps if not res.get("warmup")]
            per[(split, sha)][m] = {
                "n": len(meas),
                "enc": statistics.median(x["compress"]["elapsed_s"] for x in meas),
                "dec": statistics.median(x["decompress"]["elapsed_s"] for x in meas),
                "peak": max(max(x["compress"]["peak_memory_bytes"], x["decompress"]["peak_memory_bytes"]) for x in meas),
                "peak_med": statistics.median(max(x["compress"]["peak_memory_bytes"], x["decompress"]["peak_memory_bytes"]) for x in meas)}
    files = list(per)
    methods = sorted({m for k in files for m in per[k]})
    size = {k: int(corpus_by_sha[k[1]]["size"]) for k in files}
    out = {"files": len(files), "methods": {}}
    for m in methods:
        F = [k for k in files if m in per[k]]
        se, sd, sb = sum(per[k][m]["enc"] for k in F), sum(per[k][m]["dec"] for k in F), sum(size[k] for k in F)
        out["methods"][m] = {"files": len(F), "repeats_min": min(per[k][m]["n"] for k in F),
                             "encode_MiB_s": sb / (2 ** 20 * se), "decode_MiB_s": sb / (2 ** 20 * sd),
                             "peak_bytes_max": max(per[k][m]["peak"] for k in F),
                             "peak_bytes_median_file": statistics.median(per[k][m]["peak_med"] for k in F)}
    return out, per, size


def ratios(per, files, a, b, which):
    return sum(per[k][a][which] for k in files) / sum(per[k][b][which] for k in files)


def main() -> None:
    run, pkg = Path(sys.argv[1]), Path(sys.argv[2])
    corpus, svgx, comp, brotli_job, timing, failed_attempts = load(run)
    rows = per_file_rows(corpus, svgx, comp, brotli_job)
    N = {"run_id": run.name, "failed_attempts": failed_attempts, "files_total": len(rows)}
    N["verification"] = {
        "files": len(rows),
        "restored_both_decoders_all_arms": sum(r["restored_both_decoders_all_arms"] for r in rows),
        "raw_branch_equals_brotli_exe": sum(r["codec_raw_equals_baseline"] is True for r in rows),
        "brotli_exe_B_equal": sum(r["brotli_job_len"] == r["B"] for r in rows),
        "common_sections_equal": sum(bool(r["common_sections_equal"]) for r in rows),
        "escape_equal_IUG": sum(bool(r["escape_equal_IUG"]) for r in rows),
        "comparator_roundtrips_ok": sum(all(r[f"rt_{m}"] for m in COMPARATORS) for r in rows),
        "brotli_exe_roundtrips_ok": sum(bool(r["brotli_job_ok"]) for r in rows)}
    rows_by_split = {}
    for s in SPLITS:
        N[s], rows_by_split[s] = split_summary(rows, s)
    # cross-check against the original report tables
    xc = []
    name_map = {"G_vs_Cstar": "G_vs_Cstar(P)", "G_vs_ppmd7z": "G_vs_ppmd7z"}
    for s in SPLITS:
        with open(run / "10_tables" / f"{s}_main_comparisons.csv", encoding="utf-8", newline="") as f:
            for t in csv.DictReader(f):
                key = name_map.get(t["comparison"], t["comparison"])
                mine = N[s]["comparisons"][key]
                ok = (int(t["sum_A"]) == mine["sum_A"] and int(t["sum_C"]) == mine["sum_C"]
                      and int(t["file_wins"]) == mine["file_wins"] and int(t["file_losses"]) == mine["file_losses"]
                      and int(t["family_wins"]) == mine["family_wins"] and int(t["family_losses"]) == mine["family_losses"]
                      and abs(float(t["gain_percent"]) - mine["gain_percent"]) < 5e-5
                      and abs(float(t["file_median_gain_percent"]) - mine["file_median_gain_percent"]) < 5e-4)
                ci = {k: (float(t[k]) if t[k].replace(".", "", 1).isdigit() else None)
                      for k in ("ci995_low", "ci995_high", "bonf_low", "bonf_high")}
                mine["interval_from_run"] = ci
                xc.append({"split": s, "comparison": t["comparison"], "match": ok})
    N["crosscheck_report_tables"] = {"rows": len(xc), "all_match": all(x["match"] for x in xc),
                                     "mismatches": [x for x in xc if not x["match"]]}
    st = json.loads((run / "07_statistics" / "confirmation_statistics.json").read_text(encoding="utf-8"))
    N["bootstrap_from_run"] = {k: v for k, v in st.items() if k in ("bootstrap", "intervals", "comparisons")} or None
    # timing
    by_sha = {c["sha256"]: c for c in corpus.values()}
    T, per, size = timing_summary(timing, by_sha)
    files = list(per)
    struct_sha = {r_sha for r_sha in (corpus[r["file_id"]]["sha256"] for r in rows if r["branch_G"] == "structured")}
    raw_files = [k for k in files if k[1] not in struct_sha]
    st_files = [k for k in files if k[1] in struct_sha]
    T["structured_files_in_sample"] = len(st_files)
    T["ratios"] = {
        "G/brotli enc all": ratios(per, files, "svgx_G", "brotli11", "enc"),
        "G/brotli dec all": ratios(per, files, "svgx_G", "brotli11", "dec"),
        "G/brotli enc raw": ratios(per, raw_files, "svgx_G", "brotli11", "enc"),
        "G/brotli dec raw": ratios(per, raw_files, "svgx_G", "brotli11", "dec"),
        "G/brotli enc structured": ratios(per, st_files, "svgx_G", "brotli11", "enc"),
        "G/brotli dec structured": ratios(per, st_files, "svgx_G", "brotli11", "dec"),
        "G/P dec all": ratios(per, files, "svgx_G", "svgx_P", "dec"),
        "G/P dec structured": ratios(per, st_files, "svgx_G", "svgx_P", "dec"),
        "G/P enc all": ratios(per, files, "svgx_G", "svgx_P", "enc")}
    N["timing"] = T
    N["environment"] = json.loads((run / "01_protocol" / "environment.json").read_text(encoding="utf-8"))
    fz = json.loads((run / "01_protocol" / "freeze.json").read_text(encoding="utf-8"))
    N["freeze"] = {k: fz.get(k) for k in ("design_id", "build_id", "frozen_utc")}
    N["freeze"]["bound_files"] = len(fz.get("bound_files", {}))
    licenses = Counter(c["license"] for c in corpus.values())
    N["corpus_licenses"] = dict(licenses)
    N["corpus_sources"] = len({c["source_id"] for c in corpus.values()})
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "numbers.json").write_text(json.dumps(N, indent=1, default=str), encoding="utf-8")
    td = pkg / "tables"
    td.mkdir(exist_ok=True)
    cols = ["comparison", "files", "sum_A", "sum_C", "saved_bytes", "gain_percent", "file_median_gain_percent",
            "file_wins", "file_ties", "file_losses", "family_wins", "family_ties", "family_losses", "families"]
    for s in SPLITS:
        with open(td / f"main_comparisons_{s}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for name, c in N[s]["comparisons"].items():
                w.writerow([name, N[s]["files"]] + [c[k] if not isinstance(c[k], float) else f"{c[k]:.4f}" for k in cols[2:]])

    # ---- figure data ----
    fd = pkg / "figure_data"
    fd.mkdir(exist_ok=True)
    R = rows_by_split["confirmation"]
    with open(fd / "fig3_file_gain_vs_size_confirmation.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file_id", "category", "family", "orig_len", "B", "C_G", "branch_G", "eligible", "gain_percent"])
        for r in sorted(R, key=lambda r: r["file_id"]):
            w.writerow([r["file_id"], r["category"], r["family"], r["orig_len"], r["B"], r["C_G"], r["branch_G"],
                        int(r["eligible"]), f"{100.0 * (r['B'] - r['C_G']) / r['B']:.6f}"])
    fam = defaultdict(lambda: [0, 0, 0, set()])
    for r in R:
        x = fam[r["family"]]
        x[0] += r["B"] - r["C_G"]; x[1] += r["B"]; x[2] += 1; x[3].add(r["category"])
    with open(fd / "fig4_family_saving_confirmation.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "family", "categories", "files", "sum_B", "saved_bytes", "cumulative_share"])
        tot = sum(v[0] for v in fam.values())
        cum = 0
        for i, (k, v) in enumerate(sorted(fam.items(), key=lambda kv: (-kv[1][0], kv[0])), 1):
            cum += v[0]
            w.writerow([i, k, "+".join(sorted(v[3])), v[2], v[1], v[0], f"{cum / tot:.6f}"])
    with open(fd / "fig4_category_gain_confirmation.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "files", "families", "structured_G", "gain_percent", "ceiling_percent"])
        for cat, v in N["confirmation"]["by_category"].items():
            w.writerow([cat, v["files"], v["families"], v["structured_G"], f"{v['gain_percent']:.6f}", f"{v['ceiling_percent']:.6f}"])
    with open(fd / "fig5_decomposition_confirmation.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["quantity", "bytes"])
        c = N["confirmation"]
        for k in ("sum_B", "sum_C_D", "sum_C_P", "sum_C_I", "sum_C_U", "sum_C_G", "sum_O"):
            w.writerow([k, c[k]])
    print(json.dumps({"files": len(rows), "crosscheck": N["crosscheck_report_tables"], "verification": N["verification"]}, indent=1))


if __name__ == "__main__":
    main()

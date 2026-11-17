"""Offline report builder: regenerates every table, figure, statistic and the EN/UZ reports of one
run from its per-file ledger. Never launches codec jobs.

    python reporting/build.py --run-dir results/<run_id>
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reporting import stats as S  # noqa: E402
from runner.common import atomic_write_json, atomic_write_text, read_json, sha256_bytes, utc_now  # noqa: E402
from runner.jobs import Ledger  # noqa: E402
from runner.results import set_status  # noqa: E402

PROFILES = ["D", "P", "I", "U", "G"]
EXTERNAL = ["xwrt_l6", "xz9e", "ppmd7z", "zstd19", "gzip9"]
SPEED_ONLY = ["zstd1", "gzip1"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"


# ----------------------------------------------------------------------------- collection

def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def collect(run: Path) -> dict:
    """Per-file rows per split from the ledger and the run's corpus manifests."""
    led = Ledger(run / "ledger.sqlite")
    try:
        size_rows = led.rows("task='size' AND status='done'")
        timing_rows = led.rows("task='timing' AND status='done'")
        all_rows = led.rows()
        attempts = led.attempts()
        events = led.events()
    finally:
        led.close()
    out = {"splits": {}, "timing": timing_rows, "jobs": all_rows, "attempts": attempts, "events": events}
    by = {}
    for r in size_rows:
        by.setdefault((r["split"], r["input_sha256"]), {})[r["method"]] = r["result"]
    for split in ("pilot", "confirmation"):
        man = read_manifest(run / "02_corpus" / f"{split}.csv")
        if not man:
            continue
        rows, missing = [], []
        for m in man:
            res = by.get((split, m["sha256"]), {})
            pr = res.get("svgx")
            if pr is None:
                missing.append({"file_id": m["file_id"], "method": "svgx"})
                continue
            st = pr["stats"]
            row = {"file_id": m["file_id"], "split": split, "sha256": m["sha256"], "category": m["category"],
                   "family": m["family"], "orig_len": int(m["size"]), "eligible": st["eligible"],
                   "file_reason": st["file_reason"] or "", "blocks": st["blocks"], "B": pr["B"],
                   "O": min(pr["profiles"][p]["invariants"]["O"] for p in PROFILES)}
            ok = pr["codec_raw_equals_baseline"]
            for p in PROFILES:
                pp = pr["profiles"][p]
                row[f"C_{p}"] = pp["C"]
                row[f"F_{p}"] = pp["invariants"]["forced_len"] if pp["invariants"]["forced_len"] is not None else ""
                row[f"branch_{p}"] = pp["invariants"]["branch"]
                row[f"esc_{p}"] = st["profiles"].get(p, {}).get("escape_count", 0) if st["profiles"] else 0
                ok = ok and pp["invariants"]["ok"] and pp["verify_final"]["native_ok"] and pp["verify_final"]["reference_ok"]
                if pp["verify_forced"] is not None:
                    ok = ok and pp["verify_forced"]["native_ok"] and pp["verify_forced"]["reference_ok"]
            for e in EXTERNAL + SPEED_ONLY:
                er = res.get(e)
                if er and er.get("available") and er.get("roundtrip_ok"):
                    row[f"E_{e}"] = er["len"]
                else:
                    row[f"E_{e}"] = ""
                    if not (er and not er.get("available")):
                        missing.append({"file_id": m["file_id"], "method": e})
            row["verified"] = bool(ok)
            row["roles"] = st.get("roles") or []
            row["mode_counts"] = (st.get("common") or {}).get("mode_counts", [0, 0, 0, 0])
            rows.append(row)
        out["splits"][split] = {"rows": rows, "manifest": man, "missing": missing}
    return out


# ----------------------------------------------------------------------------- statistics

def split_stats(rows: list[dict], cfg: dict, cstar: str | None, confirmatory: bool) -> dict:
    res = {"n": len(rows), "comparisons": {}, "ceiling": {}, "forced": {}, "fallback": {}, "styles": {}}
    comps = {"G_vs_brotli11": ("B", "C_G"), "G_vs_U": ("C_U", "C_G"), "G_vs_I": ("C_I", "C_G"),
             "G_vs_D": ("C_D", "C_G"), "G_vs_P": ("C_P", "C_G")}
    if cstar:
        comps["G_vs_Cstar"] = (f"C_{cstar}", "C_G")
    for p in ["D", "P", "I", "U"]:
        comps[f"{p}_vs_brotli11"] = ("B", f"C_{p}")
    for name, (a, c) in comps.items():
        res["comparisons"][name] = S.summarize(rows, a, c)
    for e in EXTERNAL:
        have = [r for r in rows if r[f"E_{e}"] != ""]
        res["comparisons"][f"G_vs_{e}"] = S.summarize(have, f"E_{e}", "C_G") if have else {"available": False, "n_files": 0}
        if have and len(have) < len(rows):
            res["comparisons"][f"G_vs_{e}"]["coverage_note"] = f"{len(have)}/{len(rows)} files"
    sb = sum(r["B"] for r in rows) or 1
    so = sum(r["O"] for r in rows)
    res["ceiling"] = {"sum_B": sb, "sum_O": so, "ceiling_vs_brotli_percent": 100.0 * (sb - so) / sb}
    for p in PROFILES:
        elig = [r for r in rows if r[f"F_{p}"] != ""]
        gains = sum(max(0, r["B"] - int(r[f"F_{p}"])) for r in elig)
        losses = sum(max(0, int(r[f"F_{p}"]) - r["B"]) for r in elig)
        res["forced"][p] = {"eligible_files": len(elig), "gross_gain_bytes": gains, "gross_loss_bytes": losses}
        res["fallback"][p] = {"structured_files": sum(1 for r in rows if r[f"branch_{p}"] == "structured"),
                              "raw_files": sum(1 for r in rows if r[f"branch_{p}"] == "raw"),
                              "strict_improvements_vs_brotli": sum(1 for r in rows if r[f"C_{p}"] < r["B"])}
        res["styles"][p] = {"escapes": sum(int(r[f"esc_{p}"]) for r in rows)}
    tok = coll = 0
    hits = [0] * 8
    distinct = 0
    for r in rows:
        for ro in r["roles"]:
            tok += ro["tokens"]
            coll += ro["multi_match"]
            distinct += ro["distinct_outputs_sum"]
            hits = [h + v for h, v in zip(hits, ro["rule_hits"])]
    res["styles"]["tokens"] = tok
    res["styles"]["multi_match_tokens"] = coll
    res["styles"]["mean_distinct_outputs_per_token"] = distinct / tok if tok else None
    res["styles"]["rule_hits"] = hits
    res["pilot_targets"] = S.pilot_targets(rows) if rows else None
    if confirmatory and rows:
        st = cfg["stats"]
        contrasts = {"G_vs_Cstar": (f"C_{cstar}", "C_G"), "G_vs_U": ("C_U", "C_G"), "G_vs_brotli11": ("B", "C_G")}
        sec = {"G_vs_I": ("C_I", "C_G"), "G_vs_D": ("C_D", "C_G"), "G_vs_P": ("C_P", "C_G")}
        bs = S.bootstrap(rows, {**contrasts, **sec}, resamples=int(st["bootstrap_resamples"]), seed=int(st["bootstrap_seed"]))
        if bs["available"]:
            ints = {k: S.intervals(bs["draws"][k], float(st["marginal_level"]), int(st["n_confirmatory"]))
                    for k in list(contrasts) + list(sec)}
            res["bootstrap"] = {"m": bs["m"], "resamples": int(st["bootstrap_resamples"]), "seed": int(st["bootstrap_seed"]),
                                "generator": st["bootstrap_generator"], "quantile_method": st["quantile_method"],
                                "undefined_draws": bs["undefined"], "intervals": ints}
            res["claims"] = S.claim_criteria(rows, {k: ints[k] for k in contrasts}, cstar,
                                             coverage_exact=all(r["verified"] for r in rows))
        else:
            res["bootstrap"] = {"available": False, "reason": bs["reason"], "m": bs["m"]}
    return res


def timing_summary(timing_rows: list[dict], manifests: dict) -> dict:
    size_of = {}
    for split, sd in manifests.items():
        for m in sd:
            size_of[(split, m["sha256"])] = int(m["size"])
    per = {}
    for r in timing_rows:
        res = r["result"] or {}
        if not res.get("available") or res.get("warmup"):
            continue
        k = (r["method"], r["split"], r["input_sha256"])
        per.setdefault(k, {"c": [], "d": [], "mc": [], "md": []})
        per[k]["c"].append(res["compress"]["elapsed_s"])
        per[k]["d"].append(res["decompress"]["elapsed_s"])
        per[k]["mc"].append(res["compress"]["peak_memory_bytes"])
        per[k]["md"].append(res["decompress"]["peak_memory_bytes"])
    out = {}
    for (meth, split, sha), v in per.items():
        o = out.setdefault(meth, {"files": 0, "bytes": 0, "sum_med_c": 0.0, "sum_med_d": 0.0, "repeats": [],
                                  "peak_mem_c": [], "peak_mem_d": [], "per_file_c_tp": []})
        n = size_of.get((split, sha), 0)
        mc, md = statistics.median(v["c"]), statistics.median(v["d"])
        o["files"] += 1
        o["bytes"] += n
        o["sum_med_c"] += mc
        o["sum_med_d"] += md
        o["repeats"].append(len(v["c"]))
        o["peak_mem_c"].append(max(v["mc"]))
        o["peak_mem_d"].append(max(v["md"]))
        if mc > 0:
            o["per_file_c_tp"].append(n / (1 << 20) / mc)
    for meth, o in out.items():
        o["encode_MiB_per_s"] = o["bytes"] / (1 << 20) / o["sum_med_c"] if o["sum_med_c"] else None
        o["decode_MiB_per_s"] = o["bytes"] / (1 << 20) / o["sum_med_d"] if o["sum_med_d"] else None
        o["min_repeats"] = min(o["repeats"]) if o["repeats"] else 0
        o["peak_memory_max_bytes"] = max(o["peak_mem_c"] + o["peak_mem_d"]) if o["peak_mem_c"] else None
        tp = sorted(o["per_file_c_tp"])
        o["encode_throughput_p10_p50_p90"] = [tp[int(q * (len(tp) - 1))] for q in (0.1, 0.5, 0.9)] if tp else None
        for k in ("repeats", "peak_mem_c", "peak_mem_d", "per_file_c_tp"):
            del o[k]
    return out


# ----------------------------------------------------------------------------- outputs

def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    atomic_write_text(path, buf.getvalue())


def fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def figures(run: Path, split: str, rows: list[dict], st: dict, synthetic: bool) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"svg.hashsalt": "svgx", "font.family": "sans-serif", "font.size": 9,
                         "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.axisbelow": True})
    tag = "SYNTHETIC — " if synthetic else ""
    pdir, fdir = run / "08_plot_data", run / "09_figures"
    out = []

    def save(fig, name):
        import os
        if os.environ.get("SVGX_FIG_PNG"):  # optional raster preview for visual inspection (not published)
            fig.savefig(fdir / f"{name}.preview.png", format="png", dpi=110, bbox_inches="tight")
        for ext, meta in (("svg", {"Date": None}), ("pdf", {"CreationDate": None, "ModDate": None})):
            p = fdir / f"{name}.{ext}"
            fig.savefig(p, format=ext, metadata=meta, bbox_inches="tight")
            out.append(str(p.relative_to(run)))
        plt.close(fig)

    # 1. pooled gain of G against each comparator (with confirmation intervals when present)
    names = ["G_vs_brotli11", "G_vs_U", "G_vs_I", "G_vs_D", "G_vs_P"] + [f"G_vs_{e}" for e in EXTERNAL]
    data = []
    for n in names:
        c = st["comparisons"].get(n, {})
        if c.get("gain_percent") is None:
            continue
        iv = (st.get("bootstrap", {}).get("intervals", {}) or {}).get(n, {})
        lo, hi = (iv.get("marginal") or [None, None])
        data.append({"comparison": n, "gain_percent": c["gain_percent"], "ci_low": lo, "ci_high": hi})
    write_csv(pdir / f"{split}_gain_by_comparator.csv", data, ["comparison", "gain_percent", "ci_low", "ci_high"])
    if data:
        fig, ax = plt.subplots(figsize=(6.4, 0.32 * len(data) + 1.2))
        ys = list(range(len(data)))[::-1]
        ax.barh(ys, [d["gain_percent"] for d in data], height=0.5, color=BLUE)
        for y, d in zip(ys, data):
            right = d["gain_percent"]
            if d["ci_low"] is not None:
                ax.plot([d["ci_low"], d["ci_high"]], [y, y], color=INK, linewidth=1.2)
                ax.plot([d["ci_low"]] * 2, [y - 0.12, y + 0.12], color=INK, linewidth=1.2)
                ax.plot([d["ci_high"]] * 2, [y - 0.12, y + 0.12], color=INK, linewidth=1.2)
                right = max(right, d["ci_high"])
            ax.text(max(right, 0), y, f"  {d['gain_percent']:.2f}%", va="center", color=INK2, fontsize=8)
        ax.margins(x=0.12)
        ax.set_yticks(ys, [d["comparison"].replace("G_vs_", "vs ") for d in data])
        ax.axvline(0, color=AXIS, linewidth=1)
        ax.set_xlabel("Byte-weighted gain of G (%)")
        ax.set_title(f"{tag}{split}: pooled gain of G by comparator", color=INK, loc="left")
        save(fig, f"{split}_gain_by_comparator")
    # 2. per-file relative gain vs raw Brotli
    fg = [{"file_id": r["file_id"], "category": r["category"], "orig_len": r["orig_len"],
           "gain_percent": 100.0 * (r["B"] - r["C_G"]) / r["B"]} for r in rows if r["B"] > 0]
    write_csv(pdir / f"{split}_file_gain_vs_brotli.csv", fg, ["file_id", "category", "orig_len", "gain_percent"])
    if fg:
        fig, ax = plt.subplots(figsize=(6.4, 3.0))
        ax.hist([d["gain_percent"] for d in fg], bins=30, color=BLUE, edgecolor=SURFACE, linewidth=1)
        ax.set_xlabel("Per-file gain of G vs raw Brotli-11 (%)")
        ax.set_ylabel("Files")
        ax.set_title(f"{tag}{split}: per-file gain distribution (n={len(fg)})", color=INK, loc="left")
        save(fig, f"{split}_file_gain_hist")
        fig, ax = plt.subplots(figsize=(6.4, 3.2))
        ax.scatter([d["orig_len"] for d in fg], [d["gain_percent"] for d in fg], s=10, color=BLUE, alpha=0.7, linewidths=0)
        ax.set_xscale("log")
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.set_xlabel("Original size (bytes, log scale)")
        ax.set_ylabel("Gain vs raw Brotli-11 (%)")
        ax.set_title(f"{tag}{split}: gain by file size", color=INK, loc="left")
        save(fig, f"{split}_size_vs_gain")
    # 3. family net savings vs raw Brotli
    fo = S.family_outcomes(rows, "B", "C_G")
    fam = sorted(({"family": f, "net_bytes": v["g"], "files": v["files"]} for f, v in fo["per_family"].items()),
                 key=lambda d: d["net_bytes"])
    write_csv(pdir / f"{split}_family_net_savings.csv", fam, ["family", "net_bytes", "files"])
    if fam:
        fig, ax = plt.subplots(figsize=(6.4, 3.0))
        ax.bar(range(len(fam)), [d["net_bytes"] for d in fam], width=0.8,
               color=[BLUE if d["net_bytes"] > 0 else RED if d["net_bytes"] < 0 else MUTED for d in fam])
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.set_xticks([])
        ax.set_xlabel(f"Provenance families (sorted; wins {fo['wins']}, ties {fo['ties']}, losses {fo['losses']})")
        ax.set_ylabel("Net bytes saved vs raw Brotli")
        ax.set_title(f"{tag}{split}: family outcomes, G vs raw Brotli-11", color=INK, loc="left")
        save(fig, f"{split}_family_outcomes")
    # 4. style-only ceiling vs actual, per category
    cats = sorted({r["category"] for r in rows})
    cd = []
    for c in cats:
        rs = [r for r in rows if r["category"] == c]
        sb = sum(r["B"] for r in rs) or 1
        cd.append({"category": c, "actual_gain_percent": 100.0 * (sb - sum(r["C_G"] for r in rs)) / sb,
                   "ceiling_percent": 100.0 * (sb - sum(r["O"] for r in rs)) / sb})
    write_csv(pdir / f"{split}_ceiling_vs_actual.csv", cd, ["category", "actual_gain_percent", "ceiling_percent"])
    if cd:
        fig, ax = plt.subplots(figsize=(6.4, 3.0))
        x = list(range(len(cd)))
        ax.bar([i - 0.18 for i in x], [d["ceiling_percent"] for d in cd], width=0.34, color=AQUA, label="Style-free ceiling")
        ax.bar([i + 0.18 for i in x], [d["actual_gain_percent"] for d in cd], width=0.34, color=BLUE, label="Actual (G)")
        ax.set_xticks(x, [d["category"] for d in cd])
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.set_ylabel("Gain vs raw Brotli-11 (%)")
        ax.legend(frameon=False, labelcolor=INK2)
        ax.set_title(f"{tag}{split}: optimistic ceiling vs actual saving", color=INK, loc="left")
        save(fig, f"{split}_ceiling_vs_actual")
    return out


def tables(run: Path, split: str, rows: list[dict], st: dict) -> list[str]:
    tdir = run / "10_tables"
    order = ["G_vs_Cstar", "G_vs_U", "G_vs_brotli11", "G_vs_I", "G_vs_D", "G_vs_P"] + [f"G_vs_{e}" for e in EXTERNAL] + \
            ["D_vs_brotli11", "P_vs_brotli11", "I_vs_brotli11", "U_vs_brotli11"]
    trows = []
    for n in order:
        c = st["comparisons"].get(n)
        if not c or c.get("gain_percent") is None and not c.get("n_files"):
            continue
        iv = (st.get("bootstrap", {}).get("intervals", {}) or {}).get(n, {})
        trows.append({"comparison": n, "files": c.get("n_files"), "sum_A": c.get("sum_A"), "sum_C": c.get("sum_C"),
                      "gain_percent": fmt(c.get("gain_percent"), 4),
                      "file_median_gain_percent": fmt(c.get("file_median_relative_gain_percent"), 3),
                      "file_wins": (c.get("file_strict") or {}).get("wins"), "file_ties": (c.get("file_strict") or {}).get("ties"),
                      "file_losses": (c.get("file_strict") or {}).get("losses"),
                      "family_wins": (c.get("families") or {}).get("wins"), "family_ties": (c.get("families") or {}).get("ties"),
                      "family_losses": (c.get("families") or {}).get("losses"), "families": (c.get("families") or {}).get("m"),
                      "ci995_low": fmt((iv.get("marginal") or [None])[0], 4), "ci995_high": fmt((iv.get("marginal") or [None, None])[1], 4),
                      "bonf_low": fmt((iv.get("bonferroni") or [None])[0], 4), "bonf_high": fmt((iv.get("bonferroni") or [None, None])[1], 4)})
    cols = ["comparison", "files", "sum_A", "sum_C", "gain_percent", "file_median_gain_percent", "file_wins", "file_ties",
            "file_losses", "family_wins", "family_ties", "family_losses", "families", "ci995_low", "ci995_high", "bonf_low", "bonf_high"]
    write_csv(tdir / f"{split}_main_comparisons.csv", trows, cols)
    md = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    for r in trows:
        md += "| " + " | ".join(str(r[c]) for c in cols) + " |\n"
    atomic_write_text(tdir / f"{split}_main_comparisons.md", md)
    pcols = ["file_id", "category", "family", "orig_len", "eligible", "file_reason", "blocks", "B", "O"] + \
            [f"C_{p}" for p in PROFILES] + [f"F_{p}" for p in PROFILES] + [f"branch_{p}" for p in PROFILES] + \
            [f"esc_{p}" for p in PROFILES] + [f"E_{e}" for e in EXTERNAL + SPEED_ONLY] + ["verified", "sha256"]
    write_csv(run / "03_raw" / f"{split}_per_file.csv", rows, pcols)
    return [f"10_tables/{split}_main_comparisons.csv", f"10_tables/{split}_main_comparisons.md", f"03_raw/{split}_per_file.csv"]


def report_text(lang: str, run_id: str, synthetic: bool, scope: str, splits: dict, timing: dict, pilot_dec: dict | None,
                audit: dict) -> str:
    uz = lang == "uz"
    L = []
    title = ("# Natijalar" if uz else "# Results") + (" — SINTETIK (haqiqiy o'lchov emas)" if uz and synthetic else
                                                       " — SYNTHETIC (not a real measurement)" if synthetic else "")
    L.append(title)
    L.append("")
    L.append(("Run: `" if not uz else "Run identifikatori: `") + run_id + "`  ·  " + ("Doira: " if uz else "Scope: ") + scope +
             "  ·  " + ("Yaratildi: " if uz else "Generated: ") + utc_now())
    L.append("")
    if pilot_dec:
        L.append(("## Pilotdan keyingi qaror yozuvi" if uz else "## Dated pilot decision record"))
        L.append(("- Tanlangan amaliy nazorat C*: " if uz else "- Selected practical control C*: ") + f"**{pilot_dec['cstar']['selected']}** "
                 + f"(D={pilot_dec['cstar']['totals']['D']}, P={pilot_dec['cstar']['totals']['P']} bytes; {pilot_dec['cstar']['rule']})")
        L.append(("- Pilot xulosasi xeshi: `" if uz else "- Pilot summary hash: `") + pilot_dec["pilot_summary_sha256"] + "`")
        L.append(("- Yozilgan vaqt (UTC): " if uz else "- Recorded (UTC): ") + pilot_dec["recorded_utc"])
        L.append("")
    for split, sd in splits.items():
        st = sd["stats"]
        L.append(f"## {split}" + (f" ({st['n']} fayl)" if uz else f" ({st['n']} files)"))
        L.append("")
        hdr = ("| Taqqoslash | Fayllar | ΣA | ΣC | Yutuq % | Fayl W/T/L | Oila W/T/L | 99.5% interval | Bonferroni |" if uz else
               "| Comparison | Files | ΣA | ΣC | Gain % | File W/T/L | Family W/T/L | 99.5% interval | Bonferroni |")
        L.append(hdr)
        L.append("|---|---|---|---|---|---|---|---|---|")
        for n in ["G_vs_Cstar", "G_vs_U", "G_vs_brotli11", "G_vs_I", "G_vs_D", "G_vs_P"] + [f"G_vs_{e}" for e in EXTERNAL]:
            c = st["comparisons"].get(n)
            if not c or c.get("gain_percent") is None:
                if c is not None and c.get("available") is False:
                    L.append(f"| {n} | 0 | — | — | " + ("mavjud emas" if uz else "unavailable") + " | | | | |")
                continue
            iv = (st.get("bootstrap", {}).get("intervals", {}) or {}).get(n, {})
            fs, fm = c["file_strict"], c["families"]
            mi = iv.get("marginal")
            bi = iv.get("bonferroni")
            L.append(f"| {n} | {c['n_files']} | {c['sum_A']} | {c['sum_C']} | {c['gain_percent']:.4f} | "
                     f"{fs['wins']}/{fs['ties']}/{fs['losses']} | {fm['wins']}/{fm['ties']}/{fm['losses']} | "
                     f"{'[%.4f, %.4f]' % tuple(mi) if mi else '—'} | {'[%.4f, %.4f]' % tuple(bi) if bi else '—'} |")
        L.append("")
        ce = st["ceiling"]
        L.append(("- Uslubsiz optimistik shift (raw Brotli’ga nisbatan): " if uz else "- Style-free optimistic ceiling vs raw Brotli: ")
                 + f"{ce['ceiling_vs_brotli_percent']:.4f}%")
        pt = st.get("pilot_targets")
        if pt:
            yes, no = ("bajarildi", "bajarilmadi") if uz else ("met", "missed")
            L.append(("- 1% hajm maqsadi: " if uz else "- 1% size target: ") + (yes if pt["size_target_met"] else no)
                     + f" ({pt['gain_vs_brotli_percent']:.4f}%)")
            L.append(("- 2/3 oila kengligi maqsadi: " if uz else "- Two-thirds family breadth target: ") + (yes if pt["breadth_target_met"] else no)
                     + f" ({pt['family_wins']}/{pt['m']})")
        fb = st["fallback"]["G"]
        L.append(("- G: strukturali fayllar " if uz else "- G: structured files ") + f"{fb['structured_files']}, "
                 + ("raw fallback " if uz else "raw fallback ") + f"{fb['raw_files']}; "
                 + ("majburiy strukturali yalpi yutuq/yo'qotish: " if uz else "forced-structured gross gain/loss: ")
                 + f"{st['forced']['G']['gross_gain_bytes']}/{st['forced']['G']['gross_loss_bytes']} bytes")
        sty = st["styles"]
        L.append(("- Tokenlar: " if uz else "- Tokens: ") + f"{sty['tokens']}; " + ("ko'p qoidaga mos (to'qnashuv): " if uz else "multi-rule matches (collisions): ")
                 + f"{sty['multi_match_tokens']}; " + ("escape (G): " if uz else "escapes (G): ") + f"{sty['G']['escapes']}")
        cl = st.get("claims")
        if cl:
            L.append("")
            L.append("### " + ("Da'vo mezonlari" if uz else "Claim criteria"))
            for k, v in cl.items():
                if isinstance(v, bool):
                    L.append(f"- {k}: {'✓' if v else '✗'}")
            L.append(("- Keng muvaffaqiyat da'vosi: " if uz else "- Broad success claim: ") + ("✓" if cl["broad_success_claim"] else "✗"))
        bs = st.get("bootstrap")
        if bs and not bs.get("available", True):
            L.append(("- Bootstrap intervali mavjud emas: " if uz else "- Bootstrap interval unavailable: ") + bs["reason"])
        L.append("")
    if timing:
        L.append("## " + ("Vaqt va xotira (sovuq jarayon, mediana)" if uz else "Time and memory (cold process, per-file medians)"))
        L.append("")
        L.append("| Method | Files | Encode MiB/s | Decode MiB/s | Peak memory (bytes) |")
        L.append("|---|---|---|---|---|")
        for m, o in sorted(timing.items()):
            L.append(f"| {m} | {o['files']} | {fmt(o['encode_MiB_per_s'], 2)} | {fmt(o['decode_MiB_per_s'], 2)} | {o['peak_memory_max_bytes']} |")
        L.append("")
    L.append("## " + ("To'liqlik auditi" if uz else "Completeness audit"))
    for k, v in audit.items():
        L.append(f"- {k}: {v}")
    L.append("")
    L.append(("Qayta yaratish: `python study.py report --run-id " if uz else "Regenerate: `python study.py report --run-id ") + run_id + "`")
    return "\n".join(L) + "\n"


def build(run: Path, *, synthetic: bool | None = None) -> dict:
    run = Path(run)
    meta = read_json(run / "01_protocol" / "run.json", {}) or {}
    if synthetic is None:
        synthetic = bool(meta.get("synthetic"))
    scope = meta.get("scope", "unknown")
    cfg = meta.get("study_config") or {}
    if not cfg:
        from runner.common import study_config
        cfg = study_config()
    data = collect(run)
    pilot_dec = read_json(run / "07_statistics" / "pilot_decision.json")
    cstar = pilot_dec["cstar"]["selected"] if pilot_dec else None
    outputs = []
    splits = {}
    for split, sd in data["splits"].items():
        rows = sd["rows"]
        if split == "pilot" and cstar is None and rows:
            cstar_tmp = S.cstar_selection(rows)["selected"]
        else:
            cstar_tmp = cstar
        st = split_stats(rows, cfg, cstar_tmp, confirmatory=(split == "confirmation"))
        st["missing"] = sd["missing"]
        st["verified_files"] = sum(1 for r in rows if r["verified"])
        atomic_write_json(run / "07_statistics" / f"{split}_statistics.json", st)
        outputs.append(f"07_statistics/{split}_statistics.json")
        outputs += tables(run, split, rows, st)
        outputs += figures(run, split, rows, st, synthetic)
        abl = [{"file_id": r["file_id"], **{f"C_{p}": r[f"C_{p}"] for p in PROFILES}, **{f"esc_{p}": r[f"esc_{p}"] for p in PROFILES},
                "mode00": r["mode_counts"][0], "mode01": r["mode_counts"][1], "mode10": r["mode_counts"][2],
                "mode11": r["mode_counts"][3], "O": r["O"], "B": r["B"]} for r in rows]
        write_csv(run / "05_ablations" / f"{split}_ablations.csv", abl, list(abl[0].keys()) if abl else ["file_id"])
        vrows = [{"file_id": r["file_id"], "sha256": r["sha256"], "verified_native_and_reference": r["verified"]} for r in rows]
        write_csv(run / "04_verification" / f"{split}_verification.csv", vrows, ["file_id", "sha256", "verified_native_and_reference"])
        splits[split] = {"stats": st}
    timing = timing_summary(data["timing"], {s: d["manifest"] for s, d in data["splits"].items()})
    atomic_write_json(run / "06_performance" / "timing_summary.json", timing)
    trows = [{"key": r["key"], "method": r["method"], "split": r["split"], "repeat": r["repeat"],
              "warmup": (r["result"] or {}).get("warmup"),
              "compress_s": ((r["result"] or {}).get("compress") or {}).get("elapsed_s"),
              "decompress_s": ((r["result"] or {}).get("decompress") or {}).get("elapsed_s"),
              "compress_peak_bytes": ((r["result"] or {}).get("compress") or {}).get("peak_memory_bytes"),
              "decompress_peak_bytes": ((r["result"] or {}).get("decompress") or {}).get("peak_memory_bytes")}
             for r in data["timing"]]
    write_csv(run / "06_performance" / "timing_repeats.csv", trows, list(trows[0].keys()) if trows else ["key"])
    # failure / retry ledger and completeness audit
    att = data["attempts"]
    write_csv(run / "11_reports" / "failure_retry_ledger.csv", att, ["key", "attempt", "started_utc", "finished_utc", "status", "error"])
    statuses = {}
    for j in data["jobs"]:
        statuses[j["status"]] = statuses.get(j["status"], 0) + 1
    audit = {"job_status_counts": statuses, "failed_attempts": sum(1 for a in att if a["status"] != "done"),
             "events": len(data["events"]),
             **{f"{s}_files_verified": f"{d['stats']['verified_files']}/{d['stats']['n']}" for s, d in splits.items()},
             **{f"{s}_missing_measurements": len(d["stats"]["missing"]) for s, d in splits.items()}}
    atomic_write_json(run / "11_reports" / "completeness_audit.json", audit)
    for lang, name in (("en", "RESULTS_EN.md"), ("uz", "RESULTS_UZ.md")):
        atomic_write_text(run / "11_reports" / name, report_text(lang, run.name, synthetic, scope, splits, timing, pilot_dec, audit))
        outputs.append(f"11_reports/{name}")
    cmds = (f"# Commands (copy as-is)\n\n```powershell\n.\\report.cmd --run-id {run.name}\n.\\package.cmd --run-id {run.name}\n"
            f".\\run_experiment.cmd --resume --run-id {run.name}\n```\n\nPortable: `python study.py report --run-id {run.name}`\n")
    atomic_write_text(run / "12_reproducibility" / "COMMANDS.md", cmds)
    for sub, desc in (("03_raw", "per-file ledger tables"), ("04_verification", "verification tables"),
                      ("05_ablations", "ablation tables"), ("06_performance", "timing tables"), ("07_statistics", "statistics"),
                      ("08_plot_data", "plot CSVs"), ("09_figures", "figures"), ("10_tables", "tables"), ("11_reports", "reports")):
        n_files = sum(1 for _ in (run / sub).rglob("*") if _.is_file() and _.name != "STATUS.json")
        set_status(run, sub, "complete" if n_files else "empty", desc, coverage={"files": n_files,
                   **{s: d["stats"]["n"] for s, d in splits.items()}}, synthetic=synthetic)
    summary = {"outputs": outputs, "splits": {s: d["stats"]["n"] for s, d in splits.items()}, "audit": audit}
    summary["summary_sha256"] = sha256_bytes(json.dumps(summary, sort_keys=True).encode())
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline report builder")
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    s = build(Path(a.run_dir))
    print(json.dumps({"outputs": len(s["outputs"]), "splits": s["splits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

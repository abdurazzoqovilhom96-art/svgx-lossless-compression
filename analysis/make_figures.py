"""Draw Figs. 1-5 of the SVGX results.

Fig1 and Fig2 are schematics of the implemented method (no measured data; Fig2 uses synthetic
coordinates chosen only for illustration). Fig3-Fig5 are drawn exclusively from the saved measurements
exported by analysis/summarize_results.py (<out_dir>/figure_data/*.csv).
Usage: python -I analysis/make_figures.py analysis/output   ->  analysis/output/figures/Fig*.pdf, Fig*.png
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

MM = 1 / 25.4
FULL = 131 * MM  # figure width
plt.rcParams.update({
    "font.family": "Arial", "font.size": 8.5, "axes.titlesize": 8.5, "axes.labelsize": 8.5,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
    "pdf.fonttype": 42, "ps.fonttype": 42, "axes.linewidth": 0.6,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "lines.linewidth": 1.0,
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 600,
})
INK, INK2, GRID = "#1b1b1b", "#52514e", "#d9d8d4"
CAT = {  # validated categorical slots (dataviz validator, light surface) + marker as secondary encoding
    "illustrations": ("#2a78d6", "o", "////"),
    "maps": ("#eb6834", "s", "\\\\\\\\"),
    "diagrams": ("#1baf7a", "^", "...."),
    "icons": ("#6250d6", "D", "xxxx"),
}


def save(fig, out: Path) -> None:
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight", pad_inches=0.02, dpi=200)
    plt.close(fig)


def box(ax, x, y, w, h, text, fc="#f4f3f0", ec=INK, fs=7.2, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,rounding_size=0.012",
                                fc=fc, ec=ec, lw=0.7))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", linespacing=1.25)


def arrow(ax, p, q, style="-|>", lw=0.8, color=INK, ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=7, lw=lw, color=color,
                                 linestyle=ls, shrinkA=0, shrinkB=0))


def fig1(out: Path) -> None:
    fig = plt.figure(figsize=(FULL, 58 * MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-0.01, 1.01); ax.set_ylim(0, 1.04); ax.axis("off")
    yc, fs = 0.56, 7.4
    box(ax, 0.0, yc - 0.10, 0.10, 0.20, "SVG\nfile\n(bytes)", fc="#ffffff", bold=True, fs=fs)
    box(ax, 0.13, yc - 0.10, 0.12, 0.20, "XML scan,\npath\nparsing", fs=fs)
    box(ax, 0.28, yc - 0.12, 0.13, 0.24, "Cubic\nblocks;\ncontrol\npoints\n= holes", fs=fs)
    arrow(ax, (0.10, yc), (0.13, yc)); arrow(ax, (0.25, yc), (0.28, yc))
    ys = [0.885, 0.675, 0.465, 0.255]
    labels = ["Literal stream U\n→ Brotli", "Hole schedule\n→ Brotli",
              "Geometry: predicted\nhandles + residuals", "Spelling given value X\n(escapes → Brotli)"]
    for y, t in zip(ys, labels):
        box(ax, 0.455, y - 0.075, 0.25, 0.15, t, fs=fs)
        arrow(ax, (0.41, yc), (0.455, y))
    box(ax, 0.745, yc - 0.12, 0.11, 0.24, "Structured\nstream S\n(first byte\n0x11)", fs=fs)
    for y in ys:
        arrow(ax, (0.705, y), (0.745, yc + (y - yc) * 0.3))
    box(ax, 0.885, yc - 0.12, 0.115, 0.24, "Output\nmin(B, S);\nties → B", fc="#ffffff", bold=True, fs=fs)
    arrow(ax, (0.855, yc), (0.885, yc))
    box(ax, 0.13, 0.02, 0.575, 0.085, "Raw branch B: Brotli (quality 11, lgwin 22) of the whole file", fc="#ffffff", fs=fs)
    arrow(ax, (0.05, yc - 0.10), (0.05, 0.0625), style="-"); arrow(ax, (0.05, 0.0625), (0.13, 0.0625))
    arrow(ax, (0.705, 0.0625), (0.9425, 0.0625), style="-"); arrow(ax, (0.9425, 0.0625), (0.9425, yc - 0.12))
    save(fig, out)

def bez(p0, p1, p2, p3, n=60):
    import numpy as np
    t = np.linspace(0, 1, n)[:, None]
    P = [np.array(p, float) for p in (p0, p1, p2, p3)]
    return ((1 - t) ** 3) * P[0] + 3 * ((1 - t) ** 2) * t * P[1] + 3 * (1 - t) * t * t * P[2] + t ** 3 * P[3]


def fig2(out: Path) -> None:
    import numpy as np
    fig, axs = plt.subplots(1, 2, figsize=(FULL, 51 * MM), gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axs[0]
    J = np.array([[0, 0], [3.0, 2.0], [6.0, 1.2], [9.0, 2.6], [12.0, 1.0]], float)
    P1 = [J[0] + [0.6, 1.5], J[1] + [1.1, 0.35], J[2] + [1.2, -0.2], J[3] + [0.9, 0.5]]
    P2 = [J[1] - [1.2, 0.45], J[2] - [1.0, -0.1], J[3] - [1.3, 0.3], J[4] - [1.2, -0.6]]
    for s in range(4):
        cur = bez(J[s], P1[s], P2[s], J[s + 1])
        ax.plot(cur[:, 0], cur[:, 1], color=INK, lw=1.2, zorder=2)
        ax.plot([J[s][0], P1[s][0]], [J[s][1], P1[s][1]], color=INK2, lw=0.6, zorder=1)
        ax.plot([J[s + 1][0], P2[s][0]], [J[s + 1][1], P2[s][1]], color=INK2, lw=0.6, zorder=1)
        for P in (P1[s], P2[s]):
            ax.plot(*P, marker="o", mfc="white", mec="#2a78d6", ms=5, mew=1.1, zorder=4)
        c = J[s + 1] - J[s]
        q1 = J[s] + c / 3
        q2 = J[s + 1] - c / 3
        for q, P in ((q1, P1[s]), (q2, P2[s])):
            ax.plot(*q, marker="x", color="#eb6834", ms=5, mew=1.1, zorder=5)
            arrow(ax, tuple(q), tuple(P), color="#b4481c", lw=0.6, ls="--")
        ax.plot([J[s][0], J[s + 1][0]], [J[s][1], J[s + 1][1]], color="#eb6834", lw=0.5, ls=":", zorder=0)
    ax.plot(J[:, 0], J[:, 1], ls="none", marker="s", mfc=INK, mec=INK, ms=4.5, zorder=6)
    for i, p in enumerate(J):
        ax.annotate(f"$J_{i}$", p, xytext=(-4, -12), textcoords="offset points", fontsize=8.5)
    ax.set_ylim(-1.2, 3.6)
    ax.set_title("(a) One block of four cubic segments", loc="left", fontsize=8)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], ls="none", marker="s", color=INK, ms=4.5, label="junction (literal endpoint)"),
                       Line2D([], [], ls="none", marker="o", mfc="white", mec="#2a78d6", ms=5, label="control point (hole)"),
                       Line2D([], [], ls="none", marker="x", color="#eb6834", ms=5, label="mode-01 prediction (chord/3)"),
                       Line2D([], [], ls="--", color="#b4481c", lw=0.6, label="coded residual")],
              loc="upper center", frameon=False, ncol=1, fontsize=7.5, bbox_to_anchor=(0.5, -0.02))
    ax.set_aspect("equal"); ax.axis("off")
    ax = axs[1]
    ref = np.array([[0, 0], [1.5, 1.0], [3.0, 0.5], [4.4, 1.5], [5.6, 0.6]])
    A = np.array([[0.75, -0.40], [0.40, 0.75]]); t = np.array([1.6, 2.6])
    tgt = ref @ A.T + t
    for pts, col, lab in ((ref, INK2, "earlier block (decoded)"), (tgt, "#2a78d6", "current block")):
        for s in range(4):
            a, b = pts[s], pts[s + 1]
            c = b - a
            nrm = np.array([-c[1], c[0]]) * 0.35
            cur = bez(a, a + c / 3 + nrm, b - c / 3 + nrm, b)
            ax.plot(cur[:, 0], cur[:, 1], color=col, lw=1.2, label=lab if s == 0 else None)
        ax.plot(pts[:, 0], pts[:, 1], ls="none", marker="s", ms=4, color=col)
    for i in (0, 2, 4):
        arrow(ax, tuple(ref[i]), tuple(tgt[i]), color="#eb6834", ls=":", lw=0.8)
    ax.set_title("(b) Mode 11: affine copy", loc="left", fontsize=8)
    ax.legend(loc="upper center", frameon=False, fontsize=7.5, bbox_to_anchor=(0.5, -0.02), ncol=1)
    ax.set_ylim(-0.5, 6.6)
    ax.set_aspect("equal"); ax.axis("off")
    fig.tight_layout(w_pad=1.0)
    save(fig, out)


def fig3(pkg: Path, out: Path) -> None:
    rows = list(csv.DictReader(open(pkg / "figure_data" / "fig3_file_gain_vs_size_confirmation.csv", encoding="utf-8")))
    fig, ax = plt.subplots(figsize=(FULL, 52 * MM))
    raw = [r for r in rows if r["branch_G"] == "raw"]
    ax.scatter([int(r["orig_len"]) for r in raw], [0.0] * len(raw), s=5, marker="|", color="#9a9893", lw=0.5,
               label=f"raw branch ({len(raw)} files, gain 0)", zorder=1)
    for cat, (col, mk, _) in CAT.items():
        S = [r for r in rows if r["branch_G"] == "structured" and r["category"] == cat]
        if not S:
            continue
        ax.scatter([int(r["orig_len"]) for r in S], [float(r["gain_percent"]) for r in S], s=20, marker=mk,
                   facecolor=col, edgecolor="white", lw=0.6, label=f"{cat} ({len(S)})", zorder=3)
    ax.set_xscale("log")
    for x in (4096, 65536, 1048576):
        ax.axvline(x, color=GRID, lw=0.6, zorder=0)
    for x, lab in ((4096, "4 KiB"), (65536, "64 KiB"), (1048576, "1 MiB")):
        ax.text(x, 26.3, lab, fontsize=7.8, color=INK2, va="bottom", ha="center", clip_on=False)  # above the frame
    ax.set_ylim(-1.5, 26)
    ax.set_xlabel("Original file size (bytes, log scale)")
    ax.set_ylabel("Per-file saving of G vs Brotli-11 (%)")
    ax.yaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
    ax.legend(loc="upper left", frameon=False, ncol=1, bbox_to_anchor=(0.0, 0.90))
    save(fig, out)


def fig4(pkg: Path, out: Path) -> None:
    fam = list(csv.DictReader(open(pkg / "figure_data" / "fig4_family_saving_confirmation.csv", encoding="utf-8")))
    cat = list(csv.DictReader(open(pkg / "figure_data" / "fig4_category_gain_confirmation.csv", encoding="utf-8")))
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL, 50 * MM), gridspec_kw={"width_ratios": [1, 1.15]})
    pos = [r for r in fam if int(r["saved_bytes"]) > 0]
    xs = [int(r["rank"]) for r in pos]
    ys = [100 * float(r["cumulative_share"]) for r in pos]
    a.step(xs, ys, where="post", color="#2a78d6", lw=1.3)
    a.plot(xs, ys, ls="none", marker="o", ms=3, color="#2a78d6")
    for k in (1, 3, 5):
        a.annotate(f"top {k}: {ys[k - 1]:.1f} %", (k, ys[k - 1]), xytext=(8, -10 if k > 1 else -4),
                   textcoords="offset points", fontsize=8, color=INK)
    a.set_xlim(0.5, len(pos) + 0.5); a.set_ylim(0, 102)
    a.set_xticks([1, 3, 5, 10, 15, len(pos)])
    a.set_xlabel(f"Family rank ({len(pos)} of {len(fam)} families save bytes)")
    a.set_ylabel("Cumulative share of total saving (%)")
    a.yaxis.grid(True, color=GRID, lw=0.5); a.set_axisbelow(True)
    a.set_title("(a) Concentration of the saving", loc="left")
    names = [r["category"] for r in cat]
    import numpy as np
    x = np.arange(len(names))
    for i, r in enumerate(cat):
        col, _, hatch = CAT[r["category"]]
        b.bar(i - 0.19, float(r["gain_percent"]), width=0.36, color=col, edgecolor="white", lw=0.6)
        b.bar(i + 0.19, float(r["ceiling_percent"]), width=0.36, facecolor="white", edgecolor=col, hatch=hatch, lw=0.8)
        b.text(i - 0.19, float(r["gain_percent"]) + 0.08, f"{float(r['gain_percent']):.2f}", ha="center", fontsize=7)
        b.text(i + 0.19, float(r["ceiling_percent"]) + 0.32, f"{float(r['ceiling_percent']):.2f}", ha="center", fontsize=7)
    b.set_xticks(x)
    b.set_xticklabels([f"{r['category'][:5] + '.' if len(r['category']) > 6 else r['category']}\n({r['files']}; {r['structured_G']})" for r in cat], fontsize=7.5)
    b.set_ylabel("Saving vs Brotli-11 (%)")
    from matplotlib.patches import Patch
    b.legend(handles=[Patch(facecolor="#777", label="G (measured)"),
                      Patch(facecolor="white", edgecolor="#777", hatch="////", label="free-spelling bound O")],
             frameon=False, loc="upper right")
    b.set_ylim(0, 5.6)
    b.yaxis.grid(True, color=GRID, lw=0.5); b.set_axisbelow(True)
    b.set_title("(b) Saving by category", loc="left")
    fig.tight_layout(w_pad=2.0)
    save(fig, out)


def fig5(pkg: Path, out: Path) -> None:
    d = {r["quantity"]: int(r["bytes"]) for r in csv.DictReader(open(pkg / "figure_data" / "fig5_decomposition_confirmation.csv", encoding="utf-8"))}
    B = d["sum_B"]
    arms = [("D  explicit descriptors", d["sum_C_D"]), ("P  previous descriptor", d["sum_C_P"]),
            ("I  rule identifiers", d["sum_C_I"]), ("U  grouped, max weight", d["sum_C_U"]),
            ("G  grouped, summed weights", d["sum_C_G"])]
    fig, ax = plt.subplots(figsize=(FULL, 44 * MM))
    O = B - d["sum_O"]
    ys = list(range(len(arms)))[::-1]
    for y, (lab, c) in zip(ys, arms):
        sv = B - c
        ax.barh(y, sv / 1000, height=0.6, color="#2a78d6" if lab.startswith("G") else "#8fb3e3", edgecolor="white")
        ax.text(sv / 1000 - 6, y, f"{sv:,} B  ({100 * sv / B:.3f} %)", va="center", ha="right", fontsize=8,
                color="white" if lab.startswith("G") else INK)
    ax.axvline(O / 1000, color="#eb6834", ls="--", lw=1.0)
    ax.text(O / 1000 + 6, len(arms) - 1.0, f"free-spelling\nbound O:\n{O:,} B\n({100 * O / B:.3f} %)", fontsize=8,
            color="#b4481c", va="top")
    ax.set_yticks(ys); ax.set_yticklabels([a for a, _ in arms])
    ax.set_xlim(0, 700)
    ax.set_xlabel("Bytes saved relative to Brotli-11, confirmation split (thousands; ΣB = %s B)" % f"{B:,}")
    ax.xaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
    save(fig, out)


def main() -> None:
    pkg = Path(sys.argv[1])
    sub = pkg / "figures"
    sub.mkdir(parents=True, exist_ok=True)
    fig1(sub / "Fig1.pdf")
    fig2(sub / "Fig2.pdf")
    fig3(pkg, sub / "Fig3.pdf")
    fig4(pkg, sub / "Fig4.pdf")
    fig5(pkg, sub / "Fig5.pdf")
    print("ok")


if __name__ == "__main__":
    main()

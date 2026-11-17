"""Draw Figs. 1-6 of the SVGX results.

Figures are drawn at a fixed printed width (one column 76 mm, full width 160 mm) with 8 pt labels.
Fig1 is a schematic of the implemented encoder; its path-data strip is the beginning of a real path of the example file.
Fig2 and Fig6 are drawn from the junctions, predictions and control points of one corpus file as recovered by the
reference decoder (figure_data/example_file_handles.csv; see analysis/example_file/README.md).
Fig3-Fig5 are drawn exclusively from the saved measurements exported by analysis/summarize_results.py.
Every text placed in a box is checked to lie inside it; the script stops otherwise.
Usage: python -I analysis/make_figures.py analysis/output   ->  analysis/output/figures/Fig*.pdf, Fig*.png
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch, Rectangle  # noqa: E402

MM = 1 / 25.4
COLW = 76 * MM    # one-column width
FULL = 160 * MM   # full width
plt.rcParams.update({
    "font.family": "Arial", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
    "pdf.fonttype": 42, "ps.fonttype": 42, "axes.linewidth": 0.6,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "lines.linewidth": 1.0, "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 600,
    "axes.titlelocation": "left", "axes.titlepad": 4,
})
INK, INK2, GRID, FILL = "#1b1b1b", "#52514e", "#d9d8d4", "#f4f3f0"
BLUE, ORANGE, GREEN, PURPLE, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#9a9893"
CAT = {  # validated categorical slots (light surface) + marker and hatch as secondary encoding
    "illustrations": (BLUE, "o", "////"),
    "maps": (ORANGE, "s", "\\\\\\\\"),
    "diagrams": (GREEN, "^", "...."),
    "icons": (PURPLE, "D", "xxxx"),
}
MODE_COL = {0: GRAY, 1: BLUE, 2: GREEN, 3: ORANGE}
MODE_LAB = {0: "mode 00 (zero)", 1: "mode 01 (straight)", 2: "mode 10 (smooth)", 3: "mode 11 (affine copy)"}
ZOOM = (1130.0, 1290.0, -1560.0, -1440.0)    # panel (b) of Fig6, SVG user units (y flipped)
FIG2_BLOCKS = {"straight": 1631, "copy": 6304}  # blocks of the example file shown in Fig2
_BOXES: list = []


def save(fig, out: Path, width_mm: float, relayout=None) -> None:
    """Save so that the cropped figure is exactly width_mm wide, so that at that width
    every font keeps its nominal size (>= 8 pt)."""
    for _ in range(8):
        fig.canvas.draw()
        bb = fig.get_tightbbox(fig.canvas.get_renderer())
        wt = (bb.width + 2 * 0.02) * 25.4  # pad_inches=0.02 on both sides
        if abs(wt - width_mm) < 0.15:
            break
        w, h = fig.get_size_inches()
        fig.set_size_inches(w + (width_mm - wt) / 25.4, h)
        if relayout:
            relayout()
    else:
        raise SystemExit(f"{out.name}: width did not converge ({wt:.2f} mm, target {width_mm} mm)")
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    for patch, txt in _BOXES:  # text must lie inside its box
        pb, tb = patch.get_window_extent(r), txt.get_window_extent(r)
        if not (tb.x0 >= pb.x0 and tb.x1 <= pb.x1 and tb.y0 >= pb.y0 and tb.y1 <= pb.y1):
            raise SystemExit(f"{out.name}: text overflows its box: {txt.get_text()!r}")
    _BOXES.clear()
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight", pad_inches=0.02, dpi=200)
    plt.close(fig)


def box(ax, x, y, w, h, text, fc=FILL, bold=False, fs=8):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.012", fc=fc, ec=INK, lw=0.7)
    ax.add_patch(p)
    t = ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
                fontweight="bold" if bold else "normal", linespacing=1.2)
    _BOXES.append((p, t))


def arrow(ax, p, q, style="-|>", lw=0.8, color=INK, ls="-", ms=7):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=ms, lw=lw, color=color,
                                 linestyle=ls, shrinkA=0, shrinkB=0))


def line(ax, xs, ys, lw=0.8, color=INK):
    ax.plot(xs, ys, color=color, lw=lw, solid_capstyle="butt")


def bez(p0, p1, p2, p3, n=40):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


# ----------------------------------------------------------------------------- example file data
def load_example(pkg: Path) -> list[dict]:
    rows = list(csv.DictReader(open(pkg / "figure_data" / "example_file_handles.csv", encoding="utf-8")))
    out = []
    for r in rows:
        k = 10.0 ** int(r["K"])
        v = lambda a, b: np.array([int(r[a]), -int(r[b])], float) / k  # noqa: E731  (y flipped: SVG y points down)
        j0, j1 = v("j0x", "j0y"), v("j1x", "j1y")
        h0, h1, ph0, ph1 = v("h0x", "h0y"), v("h1x", "h1y"), v("ph0x", "ph0y"), v("ph1x", "ph1y")
        out.append({"block": int(r["block"]), "mode": int(r["mode"]), "dist": int(r["ref_dist"]), "seg": int(r["seg"]),
                    "j0i": (int(r["j0x"]), int(r["j0y"])), "j1i": (int(r["j1x"]), int(r["j1y"])),
                    "j0": j0, "j1": j1, "p1": j0 + h0, "p2": j1 - h1, "q1": j0 + ph0, "q2": j1 - ph1,
                    "res": [int(r[a]) - int(r[b]) for a, b in (("h0x", "ph0x"), ("h0y", "ph0y"), ("h1x", "ph1x"), ("h1y", "ph1y"))],
                    "hk": [int(r[a]) / k for a in ("h0x", "h0y", "h1x", "h1y")], "K": int(r["K"])})
    return out


# ----------------------------------------------------------------------------- Fig. 1
PATH_EXAMPLE = [  # beginning of the third path element of the example file (document order), verbatim
    "M 179.77502,979.61937 C 183.99481,980.67437 184.21794,981.84087 188.2603,983.86197",
    "C 191.97984,985.72177 195.0132,988.88257 196.74558,992.34727 C \u2026",
]


def path_strip(fig, ax, x0, y0, dy, fs=8):
    """Draw the path data verbatim (one text object per line) and shade the control-point coordinates (holes).
    The shading is placed in points relative to the line start, so it stays aligned when the figure is resized."""
    import re
    from matplotlib.transforms import Affine2D, ScaledTranslation
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    fp = FontProperties(family="DejaVu Sans Mono")
    w = lambda n: TextPath((0, 0), "0" * n, size=fs, prop=fp).get_extents().width  # noqa: E731  (points)
    cw_pt = (w(41) - w(1)) / 40  # monospace advance per character, in points (font metrics, dpi-independent)
    for li, s in enumerate(PATH_EXAMPLE):
        y = y0 - li * dy
        ax.text(x0, y, s, fontsize=fs, family="DejaVu Sans Mono", va="baseline", ha="left", color=INK, zorder=3)
        to_px = Affine2D().scale(1 / 72) + fig.dpi_scale_trans + ScaledTranslation(x0, y, ax.transData)  # points from line start, any dpi
        after_c, pending = False, 0  # after a C: the first four numbers are control coordinates, the last two the endpoint
        for m in re.finditer(r"[A-Za-z\u2026]|-?\d+\.?\d*", s):
            tok = m.group(0)
            if tok == "C":
                after_c, pending = True, 0
            elif re.match(r"-?\d", tok):
                pending += 1
                if after_c and pending <= 4:
                    ax.add_patch(Rectangle((m.start() * cw_pt - 0.6, -2.2), len(tok) * cw_pt + 1.2, 9.2,
                                           transform=to_px, fc="#d3e3f7", ec="none", zorder=2))


def fig1(out: Path) -> None:
    fig = plt.figure(figsize=(FULL, 74 * MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    # (top) real path data
    ax.text(0.0, 0.985, "Path data (beginning of a path of the example file, Fig. 6):", fontsize=8, va="top", color=INK)
    path_strip(fig, ax, 0.012, 0.89, 0.07)
    ax.add_patch(Rectangle((0.012, 0.735), 0.016, 0.03, fc="#d3e3f7", ec="none"))
    ax.text(0.034, 0.75, "control-point coordinate: removed, coded as a hole", fontsize=8, va="center")
    ax.add_patch(Rectangle((0.46, 0.735), 0.016, 0.03, fc="white", ec=INK2, lw=0.5))
    ax.text(0.482, 0.75, "commands, endpoints, separators: literal stream U", fontsize=8, va="center")
    line(ax, [0, 1], [0.71, 0.71], lw=0.4, color=GRID)
    # (bottom) encoder
    yc = 0.43
    box(ax, 0.0, yc - 0.075, 0.08, 0.15, "SVG file\n(bytes)", fc="white", bold=True)
    box(ax, 0.10, yc - 0.075, 0.11, 0.15, "XML scan,\npath parsing")
    box(ax, 0.23, yc - 0.105, 0.13, 0.21, "Cubic blocks;\ncontrol points\n= holes")
    arrow(ax, (0.08, yc), (0.10, yc)); arrow(ax, (0.21, yc), (0.23, yc))
    ys = [0.625, 0.495, 0.365, 0.235]
    labels = ["Literal stream U \u2192 Brotli", "Hole schedule \u2192 Brotli",
              "Geometry: prediction\nresiduals (bit-packed)", "Spelling given the value\n(escapes \u2192 Brotli)"]
    bus1, bus2 = 0.377, 0.633
    line(ax, [0.36, bus1], [yc, yc]); line(ax, [bus1, bus1], [ys[-1], ys[0]])
    for y, t in zip(ys, labels):
        box(ax, 0.395, y - 0.055, 0.22, 0.11, t)
        arrow(ax, (bus1, y), (0.395, y))
        line(ax, [0.615, bus2], [y, y])
    line(ax, [bus2, bus2], [ys[-1], ys[0]])
    box(ax, 0.65, yc - 0.105, 0.14, 0.21, "Structured\nstream S\n(first byte 0x11)")
    arrow(ax, (bus2, yc), (0.65, yc))
    box(ax, 0.81, yc - 0.105, 0.19, 0.21, "Output\nC = min(B, S)\n(ties: B)", fc="white", bold=True)
    arrow(ax, (0.79, yc), (0.81, yc))
    box(ax, 0.10, 0.035, 0.69, 0.085, "Raw branch B: Brotli (quality 11, lgwin 22) of the whole file", fc="white")
    line(ax, [0.04, 0.04], [yc - 0.075, 0.0775]); arrow(ax, (0.04, 0.0775), (0.10, 0.0775))
    line(ax, [0.79, 0.905], [0.0775, 0.0775]); arrow(ax, (0.905, 0.0775), (0.905, yc - 0.105))
    save(fig, out, 160)


# ----------------------------------------------------------------------------- Fig. 2
def best_triple(J):
    """Junction triple of the reference decoder: max |det| on the integer grid, ties lexicographic."""
    best, arg = -1, None
    for a in range(5):
        for b in range(a + 1, 5):
            for c in range(b + 1, 5):
                u = (J[b][0] - J[a][0], J[b][1] - J[a][1])
                v = (J[c][0] - J[a][0], J[c][1] - J[a][1])
                d = abs(u[0] * v[1] - u[1] * v[0])
                if d > best:
                    best, arg = d, (a, b, c)
    return arg


def fig2(pkg: Path, out: Path, ex: list[dict]) -> None:
    blocks = {}
    for s in ex:
        blocks.setdefault(s["block"], []).append(s)
    fig, axs = plt.subplots(2, 1, figsize=(COLW, 112 * MM), gridspec_kw={"height_ratios": [1.15, 1]})
    # (a) mode 01 block of a river
    ax = axs[0]
    segs = sorted(blocks[FIG2_BLOCKS["straight"]], key=lambda s: s["seg"])
    assert all(s["mode"] == 1 for s in segs)
    J = [segs[0]["j0"]] + [s["j1"] for s in segs]
    for s in segs:
        c = bez(s["j0"], s["p1"], s["p2"], s["j1"])
        ax.plot(c[:, 0], c[:, 1], color=INK, lw=1.2, zorder=2)
        for jj, P, Q in ((s["j0"], s["p1"], s["q1"]), (s["j1"], s["p2"], s["q2"])):
            ax.plot([jj[0], P[0]], [jj[1], P[1]], color=GRAY, lw=0.5, zorder=1)
            ax.plot([Q[0], P[0]], [Q[1], P[1]], color=BLUE, lw=0.7, ls=(0, (2, 1.2)), zorder=3)
            ax.plot(*Q, marker="x", color=BLUE, ms=4.5, mew=1.0, zorder=5)
            ax.plot(*P, marker="o", mfc="white", mec=INK, ms=4, mew=0.8, zorder=4)
    Ja = np.array(J)
    ax.plot(Ja[:, 0], Ja[:, 1], ls="none", marker="s", color=INK, ms=4, zorder=6)
    for i, p in enumerate(J):
        ax.annotate(f"$J_{i}$", p, xytext=(3, -9), textcoords="offset points", fontsize=8)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("(a) Mode 01 on four segments of a river")
    ax.legend(handles=[Line2D([], [], ls="none", marker="s", color=INK, ms=4, label="junction (literal endpoint)"),
                       Line2D([], [], ls="none", marker="o", mfc="white", mec=INK, ms=4, label="control point (hole)"),
                       Line2D([], [], ls="none", marker="x", color=BLUE, ms=4.5, mew=1.0, label="prediction R(c/3)"),
                       Line2D([], [], ls=(0, (2, 1.2)), color=BLUE, lw=0.7, label="coded residual")],
              loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, frameon=False, handletextpad=0.4, columnspacing=1.0)
    # (b) mode 11: a settlement symbol copied from an earlier identical symbol
    ax = axs[1]
    cur = sorted(blocks[FIG2_BLOCKS["copy"]], key=lambda s: s["seg"])
    assert all(s["mode"] == 3 for s in cur)
    ref = sorted(blocks[FIG2_BLOCKS["copy"] - cur[0]["dist"]], key=lambda s: s["seg"])
    zero = all(v == 0 for s in cur for v in s["res"])
    for segs_, col, lab in ((ref, GRAY, "earlier block (decoded)"), (cur, BLUE, "current block")):
        for i, s in enumerate(segs_):
            c = bez(s["j0"], s["p1"], s["p2"], s["j1"])
            ax.plot(c[:, 0], c[:, 1], color=col, lw=1.2, label=lab if i == 0 else None, zorder=2)
        Jb = np.array([segs_[0]["j0"]] + [s["j1"] for s in segs_])
        ax.plot(Jb[:, 0], Jb[:, 1], ls="none", marker="s", color=col, ms=3.5, zorder=4)
    for s in cur:
        for P, Q in ((s["p1"], s["q1"]), (s["p2"], s["q2"])):
            ax.plot(*P, marker="o", mfc="white", mec=INK, ms=4, mew=0.8, zorder=5)
            ax.plot(*Q, marker="x", color=BLUE, ms=4.5, mew=1.0, zorder=6)
    Jr = [ref[0]["j0"]] + [s["j1"] for s in ref]
    Jc = [cur[0]["j0"]] + [s["j1"] for s in cur]
    for i in best_triple([cur[0]["j0i"]] + [s["j1i"] for s in cur]):
        arrow(ax, tuple(Jr[i]), tuple(Jc[i]), color=ORANGE, ls=(0, (1, 1.5)), lw=0.8)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("(b) Mode 11 on a settlement symbol" + (" (all residuals 0)" if zero else ""))
    ax.legend(handles=[Line2D([], [], color=GRAY, lw=1.2, label="earlier block (decoded)"),
                       Line2D([], [], color=BLUE, lw=1.2, label="current block"),
                       Line2D([], [], color=ORANGE, lw=0.8, ls=(0, (1, 1.5)), label="junction triple"),
                       Line2D([], [], ls="none", marker="x", color=BLUE, ms=4.5, mew=1.0, label="affine prediction")],
              loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, frameon=False, handletextpad=0.4, columnspacing=1.0)
    fig.tight_layout(h_pad=0.6)
    save(fig, out, 76, lambda: fig.tight_layout(h_pad=0.6))
    return zero


# ----------------------------------------------------------------------------- Fig. 3
def fig3(pkg: Path, out: Path) -> None:
    rows = list(csv.DictReader(open(pkg / "figure_data" / "fig3_file_gain_vs_size_confirmation.csv", encoding="utf-8")))
    fig, ax = plt.subplots(figsize=(COLW, 66 * MM))
    raw = [r for r in rows if r["branch_G"] == "raw"]
    hs = [ax.scatter([int(r["orig_len"]) for r in raw], [0.0] * len(raw), s=6, marker="|", color=GRAY, lw=0.5,
                     label=f"raw branch ({len(raw)}, saving 0)", zorder=1)]
    for cat, (col, mk, _) in CAT.items():
        S = [r for r in rows if r["branch_G"] == "structured" and r["category"] == cat]
        if S:
            hs.append(ax.scatter([int(r["orig_len"]) for r in S], [float(r["gain_percent"]) for r in S], s=16, marker=mk,
                                 facecolor=col, edgecolor="white", lw=0.5, label=f"{cat} ({len(S)})", zorder=3))
    ex = next(r for r in rows if r["file_id"] == "C-map-6e99fcb1eefa")
    ax.annotate("Fig. 6", (int(ex["orig_len"]), float(ex["gain_percent"])), xytext=(-30, 2), textcoords="offset points",
                fontsize=8, color=INK2, va="center", ha="right",
                arrowprops=dict(arrowstyle="-", lw=0.5, color=INK2, shrinkA=1, shrinkB=3))
    ax.set_xscale("log")
    for x, lab in ((4096, "4 KiB"), (65536, "64 KiB"), (1048576, "1 MiB")):
        ax.axvline(x, color=GRID, lw=0.6, zorder=0)
        ax.text(x, 25.6, lab, fontsize=8, color=INK2, va="bottom", ha="center")
    ax.set_ylim(-1.5, 25.5); ax.set_xlim(80, 3e7)
    ax.set_xlabel("Original file size (bytes)")
    ax.set_ylabel("Saving of G vs Brotli-11 (%)")
    ax.yaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
    fig.legend(handles=hs, loc="lower center", bbox_to_anchor=(0.55, 1.0), ncol=2, frameon=False,
               handletextpad=0.3, columnspacing=0.8, borderaxespad=0)
    fig.tight_layout()
    save(fig, out, 76, fig.tight_layout)


# ----------------------------------------------------------------------------- Fig. 4
def fig4(pkg: Path, out: Path) -> None:
    fam = list(csv.DictReader(open(pkg / "figure_data" / "fig4_family_saving_confirmation.csv", encoding="utf-8")))
    cat = list(csv.DictReader(open(pkg / "figure_data" / "fig4_category_gain_confirmation.csv", encoding="utf-8")))
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL, 58 * MM), gridspec_kw={"width_ratios": [1, 1.1]})
    pos = [r for r in fam if int(r["saved_bytes"]) > 0]
    xs = [int(r["rank"]) for r in pos]
    ys = [100 * float(r["cumulative_share"]) for r in pos]
    a.step(xs, ys, where="post", color=BLUE, lw=1.2)
    a.plot(xs, ys, ls="none", marker="o", ms=3, color=BLUE)
    for k in (1, 3, 5):
        a.annotate(f"top {k}: {ys[k - 1]:.1f} %", (k, ys[k - 1]), xytext=(7, -10 if k > 1 else -3),
                   textcoords="offset points", fontsize=8, color=INK)
    a.set_xlim(0.5, len(pos) + 0.5); a.set_ylim(0, 102)
    a.set_xticks([1, 3, 5, 10, 15, len(pos)])
    a.set_xlabel(f"Family rank ({len(pos)} of {len(fam)} families save bytes)")
    a.set_ylabel("Cumulative share of total saving (%)")
    a.yaxis.grid(True, color=GRID, lw=0.5); a.set_axisbelow(True)
    a.set_title("(a) Concentration of the saving")
    for i, r in enumerate(cat):
        col, _, hatch = CAT[r["category"]]
        g, o = float(r["gain_percent"]), float(r["ceiling_percent"])
        b.bar(i - 0.19, g, width=0.36, color=col, edgecolor="white", lw=0.5)
        b.bar(i + 0.19, o, width=0.36, facecolor="white", edgecolor=col, hatch=hatch, lw=0.8)
        b.text(i - 0.19, g + 0.08, f"{g:.2f}", ha="center", fontsize=8)
        b.text(i + 0.19, o + 0.32, f"{o:.2f}", ha="center", fontsize=8)
    b.set_xticks(range(len(cat)))
    b.set_xticklabels([f"{r['category']}\n({r['files']}; {r['structured_G']})" for r in cat])
    b.set_ylabel("Saving vs Brotli-11 (%)")
    b.legend(handles=[Patch(facecolor="#777", label="G (measured)"),
                      Patch(facecolor="white", edgecolor="#777", hatch="////", label="free-spelling bound O")],
             frameon=False, loc="upper right")
    b.set_ylim(0, 5.6)
    b.yaxis.grid(True, color=GRID, lw=0.5); b.set_axisbelow(True)
    b.set_title("(b) Saving by category")
    fig.tight_layout(w_pad=2.5)
    save(fig, out, 160, lambda: fig.tight_layout(w_pad=2.5))


# ----------------------------------------------------------------------------- Fig. 6 (example file)
def fig5_example(pkg: Path, out: Path, ex: list[dict]) -> dict:
    fig = plt.figure(figsize=(FULL, 62 * MM))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.3, 0.85], wspace=0.08)
    t = np.linspace(0, 1, 12)[:, None]
    segs = [bez(s["j0"], s["p1"], s["p2"], s["j1"], 12) for s in ex]
    cols = [MODE_COL[s["mode"]] for s in ex]
    # (a) all blocks
    a = fig.add_subplot(gs[0])
    a.add_collection(LineCollection(segs, colors=cols, lw=0.3, rasterized=True))  # 26,320 curves: 600 dpi raster, text stays vector
    a.autoscale(); a.set_aspect("equal"); a.axis("off")
    x0, x1, y0, y1 = ZOOM
    a.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec=INK, lw=0.8))
    a.set_title(f"(a) All {len({s['block'] for s in ex}):,} blocks of the file")
    # (b) detail
    b = fig.add_subplot(gs[1])
    inside = [s for s in ex if x0 - 5 <= s["j0"][0] <= x1 + 5 and y0 - 5 <= s["j0"][1] <= y1 + 5]
    b.add_collection(LineCollection([bez(s["j0"], s["p1"], s["p2"], s["j1"]) for s in inside], colors=INK, lw=0.5))
    for s in inside:
        col = MODE_COL[s["mode"]]
        for jj, P in ((s["j0"], s["p1"]), (s["j1"], s["p2"])):
            b.plot([jj[0], P[0]], [jj[1], P[1]], color=col, lw=0.4)
        b.plot([s["p1"][0], s["p2"][0]], [s["p1"][1], s["p2"][1]], ls="none", marker="o", ms=1.6, mfc="white", mec=col, mew=0.45)
    b.set_xlim(x0, x1); b.set_ylim(y0, y1); b.set_aspect("equal")
    b.set_xticks([]); b.set_yticks([])
    for sp in b.spines.values():
        sp.set_visible(True); sp.set_linewidth(0.8)
    b.set_title("(b) Detail: control points by mode")
    b.legend(handles=[Line2D([], [], color=MODE_COL[m], lw=1.6, label=MODE_LAB[m]) for m in range(4)],
             loc="upper center", bbox_to_anchor=(0.32, -0.03), ncol=2, frameon=False, handlelength=1.6, columnspacing=1.2)
    # (c) magnitudes
    c = fig.add_subplot(gs[2])
    pos = c.get_position()
    c.set_position([pos.x0 + 0.075, pos.y0 + 0.06, pos.width - 0.075, pos.height - 0.06])
    H = np.array([abs(v) for s in ex for v in s["hk"]])
    R = np.array([abs(v) / 10.0 ** s["K"] for s in ex for v in s["res"]])
    xs = np.logspace(-5, 3, 400)
    hc, rc = [(H > x).mean() for x in xs], [(R > x).mean() for x in xs]
    c.plot(xs, hc, color=GRAY, lw=1.3)
    c.plot(xs, rc, color=BLUE, lw=1.3)
    c.text(2e-5, hc[0] + 0.03, "handle (no prediction)", fontsize=8, color=INK2, va="bottom")
    c.text(2e-5, rc[0] + 0.03, "coded residual", fontsize=8, color=BLUE, va="bottom")
    c.set_xscale("log"); c.set_xlim(1e-5, 1e3); c.set_ylim(0, 1.02)
    c.set_xticks([1e-4, 1e-1, 1e2])
    c.set_xlabel("x (SVG user units)")
    c.set_ylabel("Share with |value| > x")
    c.yaxis.grid(True, color=GRID, lw=0.5); c.set_axisbelow(True)
    c.set_title("(c) Magnitude of coded values")
    save(fig, out, 160)
    return {"blocks": len({s["block"] for s in ex}), "coords": int(H.size), "zero_share": float((R == 0).mean())}


# ----------------------------------------------------------------------------- Fig. 5 (spelling decomposition)
def figS1(pkg: Path, out: Path) -> None:
    d = {r["quantity"]: int(r["bytes"]) for r in csv.DictReader(open(pkg / "figure_data" / "fig5_decomposition_confirmation.csv", encoding="utf-8"))}
    B = d["sum_B"]
    arms = [("D  explicit descriptors", d["sum_C_D"]), ("P  previous descriptor", d["sum_C_P"]),
            ("I  rule identifiers", d["sum_C_I"]), ("U  grouped, max weight", d["sum_C_U"]),
            ("G  grouped, summed weights", d["sum_C_G"])]
    fig, ax = plt.subplots(figsize=(FULL, 48 * MM))
    O = B - d["sum_O"]
    ys = list(range(len(arms)))[::-1]
    for y, (lab, cc) in zip(ys, arms):
        sv = B - cc
        ax.barh(y, sv / 1000, height=0.6, color=BLUE if lab.startswith("G") else "#8fb3e3", edgecolor="white")
        ax.text(sv / 1000 - 6, y, f"{sv:,} B  ({100 * sv / B:.3f} %)", va="center", ha="right", fontsize=8,
                color="white" if lab.startswith("G") else INK)
    ax.axvline(O / 1000, color=ORANGE, ls="--", lw=1.0)
    ax.text(O / 1000 + 6, len(arms) - 1.0, f"free-spelling\nbound O:\n{O:,} B\n({100 * O / B:.3f} %)", fontsize=8,
            color="#b4481c", va="top")
    ax.set_yticks(ys); ax.set_yticklabels([a for a, _ in arms])
    ax.set_xlim(0, 700)
    ax.set_xlabel("Bytes saved relative to Brotli-11, confirmation split (thousands; \u03a3B = %s B)" % f"{B:,}")
    ax.xaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
    fig.tight_layout()
    save(fig, out, 160, fig.tight_layout)


def main() -> None:
    pkg = Path(sys.argv[1])
    out = pkg / "figures"
    out.mkdir(parents=True, exist_ok=True)
    ex = load_example(pkg)
    fig1(out / "Fig1.pdf")
    zero = fig2(pkg, out / "Fig2.pdf", ex)
    fig3(pkg, out / "Fig3.pdf")
    fig4(pkg, out / "Fig4.pdf")
    figS1(pkg, out / "Fig5.pdf")
    facts = fig5_example(pkg, out / "Fig6.pdf", ex)
    print("ok", facts, "fig2b residuals all zero:", zero)


if __name__ == "__main__":
    main()

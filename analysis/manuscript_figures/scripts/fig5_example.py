"""Fig. 5 with the real rendering of the example file (card style of Figs 1-4). Vector PDF + embedded renders, 160 mm wide.
(a) the file as rendered from the original SVG; (b) a window of the same render with the decoded junctions, handles and
control points drawn on top (exact coordinates from figure_data/fig5_example_handles.csv, incl. the file's own group
translations); (c) magnitude of coded values. Every number is recomputed and asserted.
Usage: py -3 fig5_example.py <example_file_handles.csv> <original.svg> <full.png> <zoom.png> <out.pdf>"""
import csv, re, sys
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, Rectangle

CSV, SVG, FULL, ZOOMPNG, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5])
plt.rcParams.update({"font.family": "Arial", "font.size": 7.5, "pdf.fonttype": 42, "ps.fonttype": 42,
                     "axes.linewidth": 0.6, "savefig.dpi": 600, "mathtext.default": "regular"})
INK, INK2, GRID = "#1b1b1b", "#52514e", "#e1e6ee"
BLUE, ORANGE, GREEN, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#9a9893"
MODE_COL = {0: GRAY, 1: BLUE, 2: GREEN, 3: ORANGE}
MODE_NAME = {0: "00 zero", 1: "01 straight", 2: "10 smooth", 3: "11 affine"}
WIN = (1130.0, 1290.0, 1440.0, 1560.0)   # x0, x1, y0, y1 in SVG user units (y down), as in the render of zoom.png
SVG_W, SVG_H = 2604.1531, 2213.8298

# ------------------------------------------------------------------------------ data
rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
g = lambda n: np.array([int(r[n]) for r in rows], float)
k = 10.0 ** np.array([int(r["K"]) for r in rows])
block = np.array([int(r["block"]) for r in rows]); mode = np.array([int(r["mode"]) for r in rows])
seg = np.array([int(r["seg"]) for r in rows])
j0 = np.c_[g("j0x") / k, g("j0y") / k]; j1 = np.c_[g("j1x") / k, g("j1y") / k]
h0 = np.c_[g("h0x") / k, g("h0y") / k]; h1 = np.c_[g("h1x") / k, g("h1y") / k]
H = np.abs(np.c_[g("h0x"), g("h0y"), g("h1x"), g("h1y")]) / k[:, None]
R = np.abs(np.c_[g("h0x") - g("ph0x"), g("h0y") - g("ph0y"), g("h1x") - g("ph1x"), g("h1y") - g("ph1y")]) / k[:, None]
bm = {}
for b_, m_ in zip(block.tolist(), mode.tolist()): bm[b_] = m_
cnt = {m: sum(1 for v in bm.values() if v == m) for m in range(4)}
zero, lt = float((R == 0).mean()), float((R < H).mean())
assert len(bm) == 6580 and [cnt[m] for m in range(4)] == [7, 1556, 1058, 3959], cnt
assert H.size == 105280 and f"{100*zero:.1f}" == "41.0" and f"{100*lt:.1f}" == "85.9"

# owner path and group translation of every block (so the overlay sits exactly on the render)
NS = "{http://www.w3.org/2000/svg}"
paths = []
def walk(el, tx, ty):
    t = el.get("transform")
    if t:
        m = re.fullmatch(r"\s*translate\(\s*([-\d.eE]+)[ ,]+([-\d.eE]+)\s*\)\s*", t); assert m, t
        tx, ty = tx + float(m.group(1)), ty + float(m.group(2))
    if el.tag == NS + "path" and el.get("d"): paths.append((el.get("d"), (tx, ty)))
    for c in el: walk(c, tx, ty)
walk(ET.parse(SVG).getroot(), 0.0, 0.0)
num = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
own = {}
for i, (d, _) in enumerate(paths):
    t_ = num.findall(d)
    for a, b in zip(t_, t_[1:]): own.setdefault((Decimal(a).normalize(), Decimal(b).normalize()), set()).add(i)
blk_path, prev = {}, 0
first = {}
for i in range(len(rows)):
    if seg[i] == 0: first[int(block[i])] = i
for b_ in sorted(first):
    i = first[b_]; K = int(rows[i]["K"])
    key = (Decimal(int(rows[i]["j0x"])).scaleb(-K).normalize(), Decimal(int(rows[i]["j0y"])).scaleb(-K).normalize())
    cand = sorted(x for x in own[key] if x >= prev); assert cand, b_
    blk_path[b_] = cand[0]; prev = cand[0]
tr = np.array([paths[blk_path[int(b_)]][1] for b_ in block])
npaths_with_blocks = len(set(blk_path.values()))
j0t, j1t = j0 + tr, j1 + tr
p1t, p2t = j0t + h0, j1t - h1
B_ORIG, C_G = 3438750, 683976
cs = list(csv.DictReader(open(Path(CSV).parent / "fig3_file_gain_vs_size_confirmation.csv", encoding="utf-8")))
ex = next(r for r in cs if r["file_id"] == "C-map-6e99fcb1eefa")
assert int(ex["orig_len"]) == B_ORIG and int(ex["C_G"]) == C_G and f"{float(ex['gain_percent']):.1f}" == "16.8"
BROT = int(ex["B"])

def bez(a, b, c, d, n=60):
    t = np.linspace(0, 1, n)[None, :, None]
    a, b, c, d = (v[:, None, :] for v in (a, b, c, d))
    return (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d

# ------------------------------------------------------------------------------ canvas
WM, HM = 160.0, 72.0
fig = plt.figure(figsize=(WM / 25.4, HM / 25.4), facecolor="white")
bg = fig.add_axes([0, 0, 1, 1], zorder=0); bg.set_xlim(0, WM); bg.set_ylim(0, HM); bg.axis("off")
rend = fig.canvas.get_renderer()
wmm = lambda t: t.get_window_extent(rend).width / fig.dpi * 25.4
def axmm(x, y, w, h, **kw): return fig.add_axes([x / WM, y / HM, w / WM, h / HM], **kw)
grad = np.linspace(0, 1, 256)[:, None]
cmap = LinearSegmentedColormap.from_list("card", ["#f4f7fb", "#ffffff"])
CARDS = {"a": (0.0, 52.0), "b": (54.0, 54.0), "c": (110.0, 50.0)}
TITLES = {"a": "(a) The example file", "b": "(b) Detail: control points", "c": "(c) Magnitude of coded values"}
for key, (x0, w) in CARDS.items():
    card = FancyBboxPatch((x0 + 0.3, 0.3), w - 0.6, HM - 0.6, boxstyle="round,pad=0,rounding_size=2.2", fc="none", ec="#c9d3e0", lw=0.7)
    bg.add_patch(card)
    im = bg.imshow(grad, extent=(x0, x0 + w, 0, HM), cmap=cmap, aspect="auto", origin="upper", zorder=0); im.set_clip_path(card)
    t = bg.text(0, 0, TITLES[key], fontsize=8, fontweight="bold", color="white", va="center", ha="left")
    cw = wmm(t) + 5.0; assert cw <= w - 3.0, (key, cw, w)
    bg.add_patch(FancyBboxPatch((x0 + 2.0, HM - 8.4), cw, 5.6, boxstyle="round,pad=0,rounding_size=2.8", fc="#33475b", ec="none", zorder=2))
    t.set_position((x0 + 4.5, HM - 5.6)); t.set_zorder(3)
    bg.add_patch(FancyBboxPatch((x0 + 2.0, 2.0), w - 4.0, 14.0, boxstyle="round,pad=0,rounding_size=1.4", fc="white", ec="#c9d3e0", lw=0.6, zorder=1))

def rich(x, y, bold, rest, fs=6.8, color=INK):
    t1 = bg.text(x, y, bold, fontsize=fs, fontweight="bold", color=INK, va="center", ha="left", zorder=4)
    t2 = bg.text(x + wmm(t1) + 0.9, y, rest, fontsize=fs, color=color, va="center", ha="left", zorder=4)
    return t2
def fits(t, x_right):
    assert t.get_window_extent(rend).x1 / fig.dpi * 25.4 <= x_right, (t.get_text(), x_right)

# ------------------------------------------------------------------------------ (a) real render of the file
ah = 48.0 * SVG_H / SVG_W
ax = axmm(2.0, 62.0 - ah, 48.0, ah, zorder=2)
ax.imshow(plt.imread(FULL), extent=(0, SVG_W, SVG_H, 0), aspect="auto", interpolation="antialiased")
ax.set_xlim(0, SVG_W); ax.set_ylim(SVG_H, 0); ax.set_xticks([]); ax.set_yticks([])
for sp in ax.spines.values(): sp.set_color("#c9d3e0"); sp.set_linewidth(0.6)
x0z, x1z, y0z, y1z = WIN
ax.add_patch(Rectangle((x0z, y0z), x1z - x0z, y1z - y0z, fill=False, ec="white", lw=2.0, zorder=5))
ax.add_patch(Rectangle((x0z, y0z), x1z - x0z, y1z - y0z, fill=False, ec=INK, lw=0.9, zorder=6))
rows_a = [13.2, 8.9, 4.6]
r1 = rich(4.4, rows_a[0], "File:Sibiu County 1937.svg", "", 6.8)
r2 = rich(4.4, rows_a[1], f"{B_ORIG:,} B", f"· {len(bm):,} blocks", 6.8); fits(r2, 50.4)
r3 = rich(4.4, rows_a[2], f"G {C_G:,} B", f"(Brotli-11 {BROT:,} B)", 6.8); fits(r3, 50.4)

# ------------------------------------------------------------------------------ (b) real detail + decoded geometry
bh = 50.0 * (y1z - y0z) / (x1z - x0z)
bx = axmm(56.0, 62.0 - bh, 50.0, bh, zorder=2)
bx.imshow(plt.imread(ZOOMPNG), extent=(x0z, x1z, y1z, y0z), aspect="auto", interpolation="antialiased", zorder=1)
for sp in bx.spines.values(): sp.set_color(INK2); sp.set_linewidth(0.8)
bx.set_xticks([]); bx.set_yticks([])
inb = set()
for i in range(len(rows)):
    for P in (j0t[i], j1t[i]):
        if x0z - 5 <= P[0] <= x1z + 5 and y0z - 5 <= P[1] <= y1z + 5: inb.add(int(block[i]))
sel = np.array([int(b_) in inb for b_ in block])
cols = [MODE_COL[m] for m in mode[sel].tolist()]
bx.add_collection(LineCollection(list(bez(j0t[sel], p1t[sel], p2t[sel], j1t[sel])), colors="white", linewidths=1.3, alpha=0.55, zorder=2))
bx.add_collection(LineCollection(list(bez(j0t[sel], p1t[sel], p2t[sel], j1t[sel])), colors=INK, linewidths=0.35, zorder=3))
hs = [[a, b] for a, b in zip(j0t[sel], p1t[sel])] + [[a, b] for a, b in zip(j1t[sel], p2t[sel])]
bx.add_collection(LineCollection(hs, colors=cols + cols, linewidths=0.55, zorder=4))
P = np.r_[p1t[sel], p2t[sel]]
bx.scatter(P[:, 0], P[:, 1], s=7.5, facecolors="white", edgecolors=cols + cols, linewidths=0.6, zorder=5)
J = np.r_[j0t[sel], j1t[sel]]
bx.scatter(J[:, 0], J[:, 1], s=2.4, marker="s", c=INK, linewidths=0, zorder=6)
bx.set_xlim(x0z, x1z); bx.set_ylim(y1z, y0z)
sx, sy = x1z - 28, y1z - 9
bx.add_patch(Rectangle((sx - 3, sy - 7.5), 29, 13.5, fc="white", ec="none", alpha=0.88, zorder=7))
bx.plot([sx, sx + 20], [sy, sy], color=INK, lw=1.1, solid_capstyle="butt", zorder=8)
bx.plot([sx, sx], [sy - 1.6, sy + 1.6], color=INK, lw=0.8, zorder=8); bx.plot([sx + 20, sx + 20], [sy - 1.6, sy + 1.6], color=INK, lw=0.8, zorder=8)
bx.text(sx + 10, sy - 2.6, "20 units", fontsize=6.8, color=INK, ha="center", va="bottom", zorder=8)
bcnt = {m: len({int(b_) for b_, mm_ in zip(block[sel], mode[sel]) if mm_ == m}) for m in range(4)}
present = [m for m in range(4) if bcnt[m] > 0]; assert len(present) <= 3, bcnt
rb = [12.8, 8.7, 4.6]
bg.plot([57.6], [rb[0]], marker="s", ms=2.4, color=INK, zorder=4); bg.text(60.2, rb[0], "junction", fontsize=6.8, va="center", color=INK, zorder=4)
bg.plot([57.6], [rb[1]], marker="o", ms=3.0, mfc="white", mec=INK2, mew=0.6, zorder=4); bg.text(60.2, rb[1], "control point", fontsize=6.8, va="center", color=INK, zorder=4)
bg.plot([56.2, 59.0], [rb[2], rb[2]], color=INK2, lw=0.9, zorder=4); bg.text(60.2, rb[2], "handle", fontsize=6.8, va="center", color=INK, zorder=4)
for y, m in zip(rb, present):
    bg.plot([80.2, 83.6], [y, y], color=MODE_COL[m], lw=1.8, solid_capstyle="round", zorder=4)
    t = bg.text(85.0, y, f"{MODE_NAME[m]} · {bcnt[m]}", fontsize=6.8, va="center", color=INK, zorder=4); fits(t, 106.0)

# ------------------------------------------------------------------------------ (c) magnitudes
cx = axmm(120.5, 26.0, 37.5, 36.0, zorder=2)
cx.set_facecolor("white")
for sp in ("top", "right"): cx.spines[sp].set_visible(False)
for sp in ("left", "bottom"): cx.spines[sp].set_color(INK2); cx.spines[sp].set_linewidth(0.7)
xs = np.logspace(-7, 3, 600)
def surv(v):
    s_ = np.sort(v.ravel()); return 1 - np.searchsorted(s_, xs, side="right") / s_.size
sh, sr = surv(H), surv(R)
cx.fill_between(xs, 0, sh, color=GRAY, alpha=0.16, lw=0); cx.fill_between(xs, 0, sr, color=BLUE, alpha=0.16, lw=0)
cx.plot(xs, sh, color=GRAY, lw=1.4); cx.plot(xs, sr, color=BLUE, lw=1.4)
cx.set_xscale("log"); cx.set_xlim(1e-7, 1e3); cx.set_ylim(0, 1.04)
cx.set_xticks([1e-6, 1e-3, 1, 1e3]); cx.set_xticklabels(["$10^{-6}$", "$10^{-3}$", "$1$", "$10^{3}$"], fontsize=7.5)
cx.set_yticks([0, 0.25, 0.5, 0.75, 1.0]); cx.set_yticklabels(["0", "0.25", "0.5", "0.75", "1"], fontsize=7.5)
cx.tick_params(width=0.6, length=2.2, pad=1.5); cx.minorticks_off()
cx.yaxis.grid(True, color=GRID, lw=0.5); cx.set_axisbelow(True)
th = cx.text(2.5e-7, sh[0] + 0.03, "handle (not predicted)", fontsize=7.0, color=INK2, va="bottom")
cx.text(2.5e-7, sr[0] + 0.04, "coded residual", fontsize=7.0, color="#1f5fae", va="bottom")
assert th.get_window_extent(rend).x1 / fig.dpi * 25.4 <= 159.0
cx.set_xlabel("x (SVG user units)", fontsize=7.5, labelpad=1.5)
cx.set_ylabel("Share with |value| > x", fontsize=7.5, labelpad=1.5)
bg.text(112.6, 13.2, "of the 105,280 coordinates:", fontsize=6.8, color=INK2, va="center", ha="left", zorder=4)
rich(112.6, 9.0, f"{100*zero:.1f} %", "residual exactly 0")
rich(112.6, 4.8, f"{100*lt:.1f} %", "residual < handle")

fig.savefig(OUT, dpi=600)
fig.savefig(OUT.with_suffix(".png"), dpi=220)
print("ok", OUT, "| paths with blocks:", npaths_with_blocks, "| window blocks by mode:", bcnt, "| group translations used:", sorted({(round(a, 4), round(b, 4)) for a, b in tr.tolist()}))

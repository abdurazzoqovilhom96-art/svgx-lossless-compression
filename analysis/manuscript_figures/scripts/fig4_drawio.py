"""draw.io diagram for Fig. 4 (full width, two cards) from figure_data/fig4_*.csv and fig5_decomposition_confirmation.csv.
Plots are exact SVGs (embedded images); cards, chips and tiles are native draw.io cells. Every number is recomputed and asserted."""
import base64, csv, sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

D = Path(sys.argv[1]); OUT = Path(sys.argv[2])
fam = list(csv.DictReader(open(D / "fig4_family_saving_confirmation.csv", encoding="utf-8")))
cat = list(csv.DictReader(open(D / "fig4_category_gain_confirmation.csv", encoding="utf-8")))
dec = {r["quantity"]: int(r["bytes"]) for r in csv.DictReader(open(D / "fig5_decomposition_confirmation.csv", encoding="utf-8"))}

# ---- data checks -------------------------------------------------------------------------
assert len(fam) == 55
saved = [int(r["saved_bytes"]) for r in fam]
pos = [s for s in saved if s > 0]
assert len(pos) == 19 and all(s == 0 for s in saved[19:]) and saved[:19] == sorted(saved[:19], reverse=True)
assert sum(saved) == dec["sum_B"] - dec["sum_C_G"] == 543876
cum, run = [], 0
for s in saved:
    run += s; cum.append(100.0 * run / sum(saved))
assert all(abs(c - 100 * float(r["cumulative_share"])) < 1e-4 for c, r in zip(cum, fam)), "cumulative mismatch"
assert [f"{cum[k-1]:.1f}" for k in (1, 3, 5)] == ["28.9", "67.9", "85.4"]
assert [r["category"] for r in cat] == ["illustrations", "maps", "diagrams", "icons"]
assert sum(int(r["files"]) for r in cat) == 1076 and sum(int(r["structured_G"]) for r in cat) == 39
G = [float(r["gain_percent"]) for r in cat]; O = [float(r["ceiling_percent"]) for r in cat]
assert [f"{v:.2f}" for v in G] == ["4.29", "1.08", "0.30", "0.00"] and [f"{v:.2f}" for v in O] == ["4.47", "1.09", "0.33", "0.00"]
gG = 100 * (dec["sum_B"] - dec["sum_C_G"]) / dec["sum_B"]; gO = 100 * (dec["sum_B"] - dec["sum_O"]) / dec["sum_B"]
assert f"{gG:.3f}" == "1.366" and f"{gO:.3f}" == "1.394"

# ---- shared SVG helpers ------------------------------------------------------------------
W, H = 210, 136
INK, INK2, GRID = "#1B1B1B", "#52514E", "#E1E6EE"
BLUE = "#2A78D6"
n = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
def head(): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif" fill="none">'
def ytitle(t, cy): return f'<text transform="translate(9,{n(cy)}) rotate(-90)" font-size="8" fill="{INK}" text-anchor="middle">{t}</text>'

# ---- panel (a): cumulative share of the saving ------------------------------------------
ux = 174 / 19
pxa = lambda r: 30 + (r - 0.5) * ux
pya = lambda v: 102 - v * 0.94
a = [head(), '<rect x="30" y="8" width="176" height="94" fill="#fff"/>']
for v in range(0, 101, 20):
    a.append(f'<path d="M30,{n(pya(v))}H206" stroke="{"#9AA3AF" if v == 0 else GRID}" stroke-width="{0.8 if v == 0 else 0.5}"/>')
    a.append(f'<text x="26" y="{n(pya(v)+2.6)}" font-size="7.5" fill="{INK}" text-anchor="end">{v}</text>')
steps = f"M{n(pxa(1))},102V{n(pya(cum[0]))}"
for r in range(2, 20):
    steps += f"H{n(pxa(r))}V{n(pya(cum[r-1]))}"
steps += f"H{n(pxa(19.5))}"
a.append(f'<path d="{steps}V102H{n(pxa(1))}Z" fill="#DCE9FA"/>')
a.append(f'<path d="{steps}" stroke="{BLUE}" stroke-width="1.4" stroke-linejoin="round"/>')
dots = "".join(f"M{n(pxa(r))},{n(pya(cum[r-1]))}h0.01" for r in range(1, 20) if r not in (1, 3, 5))
big = "".join(f"M{n(pxa(r))},{n(pya(cum[r-1]))}h0.01" for r in (1, 3, 5))
a.append(f'<path d="{dots}" stroke="#fff" stroke-width="5.4" stroke-linecap="round"/><path d="{dots}" stroke="{BLUE}" stroke-width="3.8" stroke-linecap="round"/>')
a.append(f'<path d="{big}" stroke="#fff" stroke-width="8" stroke-linecap="round"/><path d="{big}" stroke="#1F5FAE" stroke-width="6" stroke-linecap="round"/>')
for r in (1, 3, 5):
    a.append(f'<text x="{n(pxa(r)+6)}" y="{n(pya(cum[r-1])+11)}" font-size="7.5" fill="{INK}">top {r}: <tspan font-weight="bold">{cum[r-1]:.1f} %</tspan></text>')
a.append(f'<path d="M30,102H206M30,8V102" stroke="{INK2}" stroke-width="0.7"/>')
for r in (1, 3, 5, 10, 15, 19):
    a.append(f'<path d="M{n(pxa(r))},102v3" stroke="{INK2}" stroke-width="0.7"/><text x="{n(pxa(r))}" y="113" font-size="7.5" fill="{INK}" text-anchor="middle">{r}</text>')
a.append(f'<text x="118" y="127" font-size="8" fill="{INK}" text-anchor="middle">Family rank (by saving)</text>')
a.append(ytitle("Cumulative share (%)", 55))
a.append("</svg>")
svgA = "".join(a)

# ---- panel (b): saving by category, G (solid) and bound O (hatched) ---------------------
pyb = lambda v: 102 - v * 18
COL = ["#2A78D6", "#EB6834", "#1BAF7A", "#8A93A0"]
GRAY = "#5B6675"
def hatch(x, y, w, h, s=3.2):
    d, a0 = "", -h
    while a0 < w:
        t0, t1 = max(0.0, -a0), min(h, w - a0)
        if t1 > t0 + 0.2:
            d += f"M{n(x+a0+t0)},{n(y+h-t0)}L{n(x+a0+t1)},{n(y+h-t1)}"
        a0 += s
    return d
b = [head(), '<rect x="30" y="8" width="176" height="94" fill="#fff"/>']
for v in range(6):
    b.append(f'<path d="M30,{n(pyb(v))}H206" stroke="{"#9AA3AF" if v == 0 else GRID}" stroke-width="{0.8 if v == 0 else 0.5}"/>')
    b.append(f'<text x="26" y="{n(pyb(v)+2.6)}" font-size="7.5" fill="{INK}" text-anchor="end">{v}</text>')
b.append(f'<path d="M30,102H206M30,8V102" stroke="{INK2}" stroke-width="0.7"/>')
for i, r in enumerate(cat):
    cx = 30 + 44 * (i + 0.5)
    for k, (val, x0) in enumerate(((G[i], cx - 16), (O[i], cx + 1))):
        h = val * 18
        if h >= 0.6:
            y0 = 102 - h
            if k == 0:
                b.append(f'<rect x="{n(x0)}" y="{n(y0)}" width="15" height="{n(h)}" fill="{COL[i]}"/>')
            else:
                b.append(f'<rect x="{n(x0+0.5)}" y="{n(y0+0.5)}" width="14" height="{n(h-0.5)}" fill="#fff" stroke="{COL[i]}" stroke-width="1"/>')
                b.append(f'<path d="{hatch(x0+0.5, y0+0.5, 14, h-0.5)}" stroke="{COL[i]}" stroke-width="0.9"/>')
        b.append(f'<text x="{n(x0+7.5)}" y="{n(102-h-2.8)}" font-size="7" fill="{INK}" text-anchor="middle">{val:.2f}</text>')
    b.append(f'<text x="{n(cx)}" y="114" font-size="7.5" fill="{INK}" text-anchor="middle" font-weight="bold">{r["category"]}</text>')
    b.append(f'<text x="{n(cx)}" y="122.5" font-size="6.8" fill="{INK2}" text-anchor="middle">{int(r["files"])} files</text>')
    b.append(f'<text x="{n(cx)}" y="131" font-size="6.8" fill="{INK2}" text-anchor="middle">{int(r["structured_G"])} structured</text>')
b.append('<rect x="98" y="9" width="106" height="26" rx="3" fill="#fff" stroke="#E1E6EE" stroke-width="0.6"/>')
b.append(f'<rect x="103" y="13" width="9" height="7" fill="{GRAY}"/><text x="116" y="19.4" font-size="7.5" fill="{INK}">G (measured)</text>')
b.append(f'<rect x="103.5" y="24.5" width="8" height="6" fill="#fff" stroke="{GRAY}" stroke-width="1"/><path d="{hatch(103.5, 24.5, 8, 6, 2.6)}" stroke="{GRAY}" stroke-width="0.8"/><text x="116" y="30.4" font-size="7.5" fill="{INK}">free-spelling bound O</text>')
b.append(ytitle("Saving vs Brotli-11 (%)", 55))
b.append("</svg>")
svgB = "".join(b)
Path(OUT.parent / "fig4a_plot.svg").write_text(svgA, encoding="utf-8")
Path(OUT.parent / "fig4b_plot.svg").write_text(svgB, encoding="utf-8")

# ---- native draw.io cells ----------------------------------------------------------------
b64 = lambda s: base64.b64encode(s.encode()).decode()
cells = []
def c(i, v, stl, x, y, w, h):
    cells.append(f'<mxCell id="{i}" value={quoteattr(v)} style={quoteattr(stl)} vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
CARD = "rounded=1;arcSize=4;fillColor=#F4F7FB;gradientColor=#FFFFFF;strokeColor=#C9D3E0;"
CHIP = "rounded=1;arcSize=50;html=1;fillColor=#33475B;strokeColor=none;fontColor=#FFFFFF;fontSize=8;"
TILE = "rounded=1;arcSize=12;html=1;whiteSpace=wrap;fillColor=#FFFFFF;strokeColor=#C9D3E0;fontFamily=Helvetica;fontColor=#1B1B1B;fontSize=7.5;"
for p, x0, chip, cw, svg, tiles in (
    ("a", 0, "(a) Concentration of the saving", 140, svgA,
     ("<b>19 of 55 families</b><br>save bytes", "<b>36 of 55 families</b><br>save nothing")),
    ("b", 238, "(b) Saving by category", 112, svgB,
     (f"<b>G, measured</b><br>{gG:.3f}&#160;% over 1,076 files", f"<b>Bound O</b><br>{gO:.3f}&#160;% over 1,076 files"))):
    c("k" + p, "", CARD, x0, 0, 222, 200)
    c("t" + p, f"<b>{chip}</b>", CHIP, x0 + 6, 6, cw, 16)
    c("i" + p, "", "shape=image;aspect=fixed;image=data:image/svg+xml," + b64(svg) + ";", x0 + 6, 26, W, H)
    c("m" + p, tiles[0], TILE, x0 + 6, 166, 104, 28)
    c("n" + p, tiles[1], TILE, x0 + 112, 166, 104, 28)
xml = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel>"
OUT.write_text(xml, encoding="utf-8")
print("ok", len(xml), "cum1,3,5 =", [round(cum[k - 1], 2) for k in (1, 3, 5)], "G,O =", round(gG, 3), round(gO, 3))

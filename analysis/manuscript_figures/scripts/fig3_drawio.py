"""draw.io diagram for Fig. 3 (full width) from figure_data/fig3_file_gain_vs_size_confirmation.csv.
The plot is an exact SVG (embedded as an image); card, chip and the per-bracket statistics are native draw.io cells.
Bracket statistics are recomputed from the CSV and asserted against Table 5."""
import base64, csv, math, sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
OUT = Path(sys.argv[2])
assert len(rows) == 1076
B = [(0, 4096, "< 4 KiB"), (4096, 65536, "4–64 KiB"), (65536, 1048576, "64 KiB–1 MiB"), (1048576, 10**12, "≥ 1 MiB")]
stats = []
for lo, hi, name in B:
    rs = [r for r in rows if lo <= int(r["orig_len"]) < hi]
    sb, sc = sum(int(r["B"]) for r in rs), sum(int(r["C_G"]) for r in rs)
    stats.append((name, len(rs), sum(r["branch_G"] == "structured" for r in rs), 100 * (sb - sc) / sb))
assert [(n, s) for _, n, s, _ in stats] == [(696, 0), (275, 9), (77, 23), (28, 7)], stats
assert [f"{g:.3f}" for *_, g in stats] == ["0.000", "0.219", "4.223", "1.065"], stats
raw = [r for r in rows if r["branch_G"] == "raw"]; st = [r for r in rows if r["branch_G"] == "structured"]
assert len(raw) == 1037 and len(st) == 39
cats = {c: [r for r in st if r["category"] == c] for c in ("illustrations", "maps", "diagrams")}
assert [len(v) for v in cats.values()] == [16, 18, 5]

W, H = 448, 186
LX0, LX1, PX0, PX1 = 2.0, 7.5, 38.0, 442.0
X = lambda b: PX0 + (math.log10(b) - LX0) / (LX1 - LX0) * (PX1 - PX0)
YV0, YV1, PY0, PY1 = -1.0, 31.5, 118.0, 10.0
assert max(float(r["gain_percent"]) for r in rows) < 30.5
Y = lambda v: PY0 + (v - YV0) / (YV1 - YV0) * (PY1 - PY0)
n = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
INK, INK2, GRID = "#1B1B1B", "#52514E", "#D9DEE6"
COL = {"illustrations": "#2A78D6", "maps": "#EB6834", "diagrams": "#1BAF7A"}
s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif" fill="none">']
edges = [X(4096), X(65536), X(1048576)]
xs = [PX0] + edges + [PX1]
for i in range(4):
    s.append(f'<rect x="{n(xs[i])}" y="8" width="{n(xs[i+1]-xs[i])}" height="138" fill="{"#F3F6FA" if i % 2 == 0 else "#FFFFFF"}"/>')
for v in (0, 5, 10, 15, 20, 25, 30):
    s.append(f'<path d="M{n(PX0)},{n(Y(v))}H{n(PX1)}" stroke="{"#9AA3AF" if v == 0 else GRID}" stroke-width="{0.8 if v == 0 else 0.5}"/>')
    s.append(f'<text x="{n(PX0-4)}" y="{n(Y(v)+2.6)}" font-size="7.5" fill="{INK}" text-anchor="end">{v}</text>')
for e in edges:
    s.append(f'<path d="M{n(e)},8V146" stroke="#B8C2CF" stroke-width="0.6" stroke-dasharray="2,2"/>')
# histogram of the raw-branch files (saving 0)
bins = [LX0 + 0.125 * k for k in range(45)]
cnt = [0] * 44
for r in raw:
    k = min(43, int((math.log10(int(r["orig_len"])) - LX0) / 0.125)); cnt[k] += 1
mx = max(cnt)
s.append(f'<rect x="{n(PX0)}" y="126" width="{n(PX1-PX0)}" height="20" fill="#E9EDF2"/>')
s.append(f'<text x="{n(PX0-4)}" y="139" font-size="7.5" fill="{INK2}" text-anchor="end">raw</text>')
for k, c in enumerate(cnt):
    if c:
        x0, x1 = X(10 ** bins[k]), X(10 ** bins[k + 1]); h = 18 * c / mx
        s.append(f'<rect x="{n(x0+0.3)}" y="{n(144-h)}" width="{n(x1-x0-0.6)}" height="{n(h)}" fill="#A8AFB8"/>')
s.append(f'<path d="M{n(PX0)},146H{n(PX1)}M{n(PX0)},8V118" stroke="{INK2}" stroke-width="0.7"/>')
for p in range(2, 8):
    x = X(10 ** p)
    s.append(f'<path d="M{n(x)},146v3" stroke="{INK2}" stroke-width="0.7"/>')
    s.append(f'<text x="{n(x)}" y="158" font-size="7.5" fill="{INK}" text-anchor="middle">10<tspan font-size="5.5" dy="-3">{p}</tspan></text>')
s.append(f'<text x="{n((PX0+PX1)/2)}" y="175" font-size="8" fill="{INK}" text-anchor="middle">Original file size (bytes, log scale)</text>')
s.append(f'<text transform="translate(10,{n((Y(30)+146)/2)}) rotate(-90)" font-size="8" fill="{INK}" text-anchor="middle">Saving of G vs Brotli-11 (%)</text>')
for c, rs in cats.items():
    for r in rs:
        x, y = X(int(r["orig_len"])), Y(float(r["gain_percent"]))
        if c == "illustrations":
            s.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="2.8" fill="{COL[c]}" stroke="#fff" stroke-width="0.6"/>')
        elif c == "maps":
            s.append(f'<rect x="{n(x-2.6)}" y="{n(y-2.6)}" width="5.2" height="5.2" fill="{COL[c]}" stroke="#fff" stroke-width="0.6"/>')
        else:
            s.append(f'<path d="M{n(x)},{n(y-3.2)}L{n(x+3)},{n(y+2.2)}L{n(x-3)},{n(y+2.2)}Z" fill="{COL[c]}" stroke="#fff" stroke-width="0.6"/>')
ex = next(r for r in rows if r["file_id"] == "C-map-6e99fcb1eefa")
ex_x, ex_y = X(int(ex["orig_len"])), Y(float(ex["gain_percent"]))
s.append(f'<path d="M{n(ex_x-4)},{n(ex_y)}H{n(ex_x-26)}" stroke="{INK2}" stroke-width="0.6"/>')
s.append(f'<text x="{n(ex_x-28)}" y="{n(ex_y+2.6)}" font-size="7.5" fill="{INK2}" text-anchor="end">Fig. 5</text>')
lg = [("c", "illustrations (16)"), ("s", "maps (18)"), ("t", "diagrams (5)"), ("h", "raw branch (1,037; saving 0)")]
for i, (k, t) in enumerate(lg):
    y = 20 + 11 * i; x = 46
    if k == "c": s.append(f'<circle cx="{x}" cy="{y}" r="2.8" fill="{COL["illustrations"]}"/>')
    if k == "s": s.append(f'<rect x="{x-2.6}" y="{y-2.6}" width="5.2" height="5.2" fill="{COL["maps"]}"/>')
    if k == "t": s.append(f'<path d="M{x},{y-3.2}L{x+3},{y+2.2}L{x-3},{y+2.2}Z" fill="{COL["diagrams"]}"/>')
    if k == "h": s.append(f'<rect x="{x-3}" y="{y-3}" width="2.4" height="6" fill="#A8AFB8"/><rect x="{x+0.4}" y="{y-1}" width="2.4" height="4" fill="#A8AFB8"/>')
    s.append(f'<text x="{x+7}" y="{y+2.6}" font-size="7.5" fill="{INK}">{t}</text>')
s.append("</svg>")
svg = "".join(s)
Path(OUT.parent / "fig3_plot.svg").write_text(svg, encoding="utf-8")

TX = "text;html=1;align=center;verticalAlign=middle;fontFamily=Helvetica;fontColor=#1B1B1B;fontSize=7.5;"
cells = []
def c(i, v, stl, x, y, w, h):
    cells.append(f'<mxCell id="{i}" value={quoteattr(v)} style={quoteattr(stl)} vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
c("card", "", "rounded=1;arcSize=3;fillColor=#F4F7FB;gradientColor=#FFFFFF;strokeColor=#C9D3E0;", 0, 0, 460, 252)
c("chip", "<b>Per-file saving, confirmation split (1,076 files)</b>", "rounded=1;arcSize=50;html=1;fillColor=#33475B;strokeColor=none;fontColor=#FFFFFF;fontSize=8;", 6, 6, 210, 16)
c("plot", "", "shape=image;aspect=fixed;image=data:image/svg+xml," + base64.b64encode(svg.encode()).decode() + ";", 6, 26, W, H)
for i, (name, nf, ns, g) in enumerate(stats):
    x0 = 6 + xs[i] + 1; w = xs[i + 1] - xs[i] - 2
    v = f"<b>{name}</b><br>{nf} files<br>{ns} structured &#183; {g:.3f}&#160;%"
    c(f"b{i}", v, "rounded=1;arcSize=12;html=1;whiteSpace=wrap;fillColor=#FFFFFF;strokeColor=#C9D3E0;fontFamily=Helvetica;fontColor=#1B1B1B;fontSize=7.5;", round(x0, 1), 214, round(w, 1), 32)
c("bl", "size<br>bracket", TX + "fontColor=#52514E;", 6, 214, 36, 32)
xml = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel>"
OUT.write_text(xml, encoding="utf-8")
print("ok", len(xml), [(nf, ns, round(g, 3)) for nm, nf, ns, g in stats])

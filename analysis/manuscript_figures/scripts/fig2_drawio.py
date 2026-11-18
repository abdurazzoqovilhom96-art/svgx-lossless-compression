"""draw.io XML for Fig. 2 from example_file_handles.csv (blocks 1631 and 6304; coordinates rounded to 0.1 px, grouped SVG styles).
Usage: py -3 fig2_drawio.py <example_file_handles.csv> <out.xml>"""
import base64, csv, sys
from pathlib import Path
from xml.sax.saxutils import quoteattr
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
blk = {}
for r in rows:
    blk.setdefault(int(r["block"]), []).append(r)
for v in blk.values():
    v.sort(key=lambda r: int(r["seg"]))
def P(r, a, b):
    k = 10.0 ** int(r["K"]); return (int(r[a]) / k, int(r[b]) / k)
def segs(b):
    o = []
    for r in blk[b]:
        j0, j1 = P(r, "j0x", "j0y"), P(r, "j1x", "j1y")
        h0, h1, q0, q1 = P(r, "h0x", "h0y"), P(r, "h1x", "h1y"), P(r, "ph0x", "ph0y"), P(r, "ph1x", "ph1y")
        o.append(dict(j0=j0, j1=j1, p1=(j0[0]+h0[0], j0[1]+h0[1]), p2=(j1[0]-h1[0], j1[1]-h1[1]),
                      q1=(j0[0]+q0[0], j0[1]+q0[1]), q2=(j1[0]-q1[0], j1[1]-q1[1]), mode=int(r["mode"]), dist=int(r["ref_dist"]),
                      res=[int(r[a]) - int(r[c]) for a, c in (("h0x","ph0x"),("h0y","ph0y"),("h1x","ph1x"),("h1y","ph1y"))],
                      ji=((int(r["j0x"]), int(r["j0y"])), (int(r["j1x"]), int(r["j1y"])))))
    return o
W, H = 210, 120
def fit(pts, pad):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    s = min((W-2*pad)/(max(xs)-min(xs)), (H-2*pad)/(max(ys)-min(ys)))
    ox = (W - s*(max(xs)-min(xs)))/2 - s*min(xs); oy = (H - s*(max(ys)-min(ys)))/2 - s*min(ys)
    return lambda p: (round(ox+s*p[0], 1), round(oy+s*p[1], 1))
n = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
pt = lambda p: n(p[0]) + "," + n(p[1])
def X(c, d=2.5):
    x, y = c; return f"M{n(x-d)},{n(y-d)}l{n(2*d)},{n(2*d)}m0,{n(-2*d)}l{n(-2*d)},{n(2*d)}"
BLUE, OR, GR, INK = "#2A78D6", "#D9661F", "#9A9893", "#1B1B1B"
A = segs(1631); assert all(s["mode"] == 1 for s in A)
T = fit([p for s in A for p in (s["j0"], s["j1"], s["p1"], s["p2"], s["q1"], s["q2"])], 12)
hand = "".join(f"M{pt(T(j))}L{pt(T(p))}" for s in A for j, p in ((s["j0"], s["p1"]), (s["j1"], s["p2"])))
curve = f"M{pt(T(A[0]['j0']))}" + "".join(f"C{pt(T(s['p1']))} {pt(T(s['p2']))} {pt(T(s['j1']))}" for s in A)
resid = "".join(f"M{pt(T(q))}L{pt(T(p))}" for s in A for p, q in ((s["p1"], s["q1"]), (s["p2"], s["q2"])))
crosses = "".join(X(T(q)) for s in A for q in (s["q1"], s["q2"]))
circ = "".join(f'<circle cx="{n(T(p)[0])}" cy="{n(T(p)[1])}" r="2.2"/>' for s in A for p in (s["p1"], s["p2"]))
J = [A[0]["j0"]] + [s["j1"] for s in A]
sq = "".join(f'<rect x="{n(T(j)[0]-1.9)}" y="{n(T(j)[1]-1.9)}" width="3.8" height="3.8"/>' for j in J)
lab = "".join(f'<text x="{n(T(j)[0]+3.2)}" y="{n(T(j)[1]+8)}">J<tspan font-size="5.5" dy="1.6" font-style="normal">{i}</tspan></text>' for i, j in enumerate(J))
svgA = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none">'
        f'<path d="{hand}" stroke="{GR}" stroke-width="0.6"/><path d="{curve}" stroke="{INK}" stroke-width="1.3"/>'
        f'<path d="{resid}" stroke="{BLUE}" stroke-width="0.8" stroke-dasharray="2.2,1.4"/><path d="{crosses}" stroke="{BLUE}"/>'
        f'<g fill="#fff" stroke="{INK}" stroke-width="0.8">{circ}</g><g fill="{INK}">{sq}</g>'
        f'<g fill="{INK}" font-family="Helvetica,Arial,sans-serif" font-size="7.5" font-style="italic">{lab}</g></svg>')
C = segs(6304); assert all(s["mode"] == 3 for s in C)
R = segs(6304 - C[0]["dist"]); assert all(v == 0 for s in C for v in s["res"])
Ji = [C[0]["ji"][0]] + [s["ji"][1] for s in C]
best, arg = -1, None
for a in range(5):
    for b in range(a+1, 5):
        for c in range(b+1, 5):
            u = (Ji[b][0]-Ji[a][0], Ji[b][1]-Ji[a][1]); v = (Ji[c][0]-Ji[a][0], Ji[c][1]-Ji[a][1])
            d = abs(u[0]*v[1]-u[1]*v[0])
            if d > best: best, arg = d, (a, b, c)
T = fit([p for s in C + R for p in (s["j0"], s["j1"], s["p1"], s["p2"])], 14)
JR = [R[0]["j0"]] + [s["j1"] for s in R]; JC = [C[0]["j0"]] + [s["j1"] for s in C]
tri = "".join(f"M{pt(T(JR[i]))}L{pt(T(JC[i]))}" for i in arg)
def cv(S): return f"M{pt(T(S[0]['j0']))}" + "".join(f"C{pt(T(s['p1']))} {pt(T(s['p2']))} {pt(T(s['j1']))}" for s in S)
def sqs(S): return "".join(f'<rect x="{n(T(j)[0]-1.8)}" y="{n(T(j)[1]-1.8)}" width="3.6" height="3.6"/>' for j in [S[0]["j0"]] + [s["j1"] for s in S])
circB = "".join(f'<circle cx="{n(T(p)[0])}" cy="{n(T(p)[1])}" r="2.2"/>' for s in C for p in (s["p1"], s["p2"]))
crB = "".join(X(T(q), 2.3) for s in C for q in (s["q1"], s["q2"]))
svgB = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none">'
        f'<defs><marker id="m" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0L6,3L0,6z" fill="#6E6E6E"/></marker></defs>'
        f'<g stroke="#6E6E6E" stroke-width="0.8" stroke-dasharray="1,1.6" marker-end="url(#m)">' + "".join(f'<path d="M{pt(T(JR[i]))}L{pt(T(JC[i]))}"/>' for i in arg) + '</g>'
        f'<path d="{cv(R)}" stroke="{GR}" stroke-width="1.3"/><path d="{cv(C)}" stroke="{OR}" stroke-width="1.3"/>'
        f'<g fill="{GR}">{sqs(R)}</g><g fill="{OR}">{sqs(C)}</g><g fill="#fff" stroke="{INK}" stroke-width="0.8">{circB}</g>'
        f'<path d="{crB}" stroke="{OR}" stroke-width="0.9"/></svg>')
b64 = lambda s: base64.b64encode(s.encode()).decode()
TX = "text;html=1;align=left;verticalAlign=middle;fontFamily=Helvetica;fontColor=#1B1B1B;fontSize=7.5;"
cells = []
def c(i, v, st, x, y, w, h):
    cells.append(f'<mxCell id="{i}" value={quoteattr(v)} style={quoteattr(st)} vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
def e(i, st, x1, y1, x2, y2):
    cells.append(f'<mxCell id="{i}" style={quoteattr(st)} edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/><mxPoint x="{x2}" y="{y2}" as="targetPoint"/></mxGeometry></mxCell>')
for p, x0, tint, edge, chip, cw, title, form, fact, svg in (
    ("a", 0, "#F2F7FE", "#BCD5F5", BLUE, 132, "(a) Mode 01: straight prediction", "&#293;<sub>0</sub> = &#293;<sub>1</sub> = <i>R</i>(<i>c<sub>s</sub></i>/3)", "Four segments of a river: 16 coordinates coded as residuals", svgA),
    ("b", 238, "#FEF5EE", "#F2C9A8", OR, 108, "(b) Mode 11: affine copy", "&#293; = <i>R</i>(<i>T</i> adj(<i>Q</i>) <i>h</i> / det <i>Q</i>)", "Copy of an identical, earlier symbol: all residuals 0", svgB)):
    c("k"+p, "", f"rounded=1;arcSize=5;fillColor={tint};gradientColor=#FFFFFF;strokeColor={edge};", x0, 0, 222, 196)
    c("t"+p, f"<b>{title}</b>", f"rounded=1;arcSize=50;html=1;fillColor={chip};strokeColor=none;fontColor=#FFFFFF;fontSize=8;", x0+6, 6, cw, 16)
    c("f"+p, form, TX + "fontSize=8;align=right;", x0+8+cw, 6, 208-cw, 16)
    c("i"+p, "", "shape=image;aspect=fixed;image=data:image/svg+xml," + b64(svg) + ";", x0+6, 26, W, H)
    c("s"+p, fact, TX + "fontColor=#3A3A3A;", x0+6, 149, 210, 12)
c("a1", "", "fillColor=#1B1B1B;strokeColor=none;", 8, 169, 5, 5); c("a1t", "junction (literal endpoint)", TX, 18, 166, 96, 11)
c("a2", "", "ellipse;fillColor=#FFFFFF;strokeColor=#1B1B1B;", 7.5, 181.5, 6, 6); c("a2t", "control point (hole)", TX, 18, 179, 96, 11)
c("a3", "&#215;", TX + f"fontSize=10;fontColor={BLUE};fontStyle=1;align=center;", 112, 165, 10, 12); c("a3t", "prediction <i>R</i>(<i>c</i>/3)", TX, 124, 166, 92, 11)
e("a4", f"endArrow=none;strokeColor={BLUE};dashed=1;", 112, 184.5, 122, 184.5); c("a4t", "coded residual", TX, 124, 179, 92, 11)
e("b1", f"endArrow=none;strokeColor={GR};strokeWidth=1.3;", 244, 171.5, 254, 171.5); c("b1t", "earlier block (decoded)", TX, 256, 166, 94, 11)
e("b2", f"endArrow=none;strokeColor={OR};strokeWidth=1.3;", 244, 184.5, 254, 184.5); c("b2t", "current block", TX, 256, 179, 94, 11)
e("b3", "endArrow=block;endSize=3;strokeColor=#6E6E6E;dashed=1;dashPattern=1 2;", 348, 171.5, 360, 171.5); c("b3t", "junction triple", TX, 362, 166, 92, 11)
c("b4", "&#215;", TX + f"fontSize=10;fontColor={OR};fontStyle=1;align=center;", 349, 178, 10, 12); c("b4t", "affine prediction", TX, 362, 179, 92, 11)
xml = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel>"
Path(sys.argv[2]).write_text(xml, encoding="utf-8")
print(len(xml), arg)

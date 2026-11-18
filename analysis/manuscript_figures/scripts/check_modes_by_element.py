import csv, re, sys
import xml.etree.ElementTree as ET
from decimal import Decimal
from collections import Counter, defaultdict
svgf, csvf = sys.argv[1], sys.argv[2]
NS = "{http://www.w3.org/2000/svg}"
paths = []
def walk(el):
    if el.tag == NS + "path" and el.get("d"): paths.append((el.get("d"), el.get("style") or "", el))
    for c in el: walk(c)
walk(ET.parse(svgf).getroot())
num = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
own = {}
for i, (d, _, _) in enumerate(paths):
    t = num.findall(d)
    for a, b in zip(t, t[1:]): own.setdefault((Decimal(a).normalize(), Decimal(b).normalize()), set()).add(i)
rows = list(csv.DictReader(open(csvf, encoding="utf-8")))
first = {int(r["block"]): r for r in rows if int(r["seg"]) == 0}
prev, owner = 0, {}
for b in sorted(first):
    r = first[b]; K = int(r["K"])
    key = (Decimal(int(r["j0x"])).scaleb(-K).normalize(), Decimal(int(r["j0y"])).scaleb(-K).normalize())
    cand = sorted(x for x in own[key] if x >= prev); owner[b] = cand[0]; prev = cand[0]
def prop(style, name):
    m = re.search(r"(?:^|;)\s*" + name + r":\s*([^;]+)", style); return m.group(1).strip() if m else None
def klass(i):
    st = paths[i][1]; fill, stroke = prop(st, "fill"), prop(st, "stroke")
    return (fill if fill else "-", stroke if stroke else "-")
tab = defaultdict(Counter)
for b, i in owner.items():
    tab[int(first[b]["mode"])][klass(i)] += 1
tot = Counter()
for m in tab: tot.update(tab[m])
for m in range(4):
    n = sum(tab[m].values()); print(f"mode {m}: {n} blocks")
    for (f, s), c in tab[m].most_common(8): print(f"    fill={f:<10} stroke={s:<10} {c:>5} ({100*c/n:.1f}%)")
print("\nall classes (blocks, share in each mode):")
for (f, s), c in tot.most_common(12):
    print(f"  fill={f:<10} stroke={s:<10} total={c:>5} | " + " ".join(f"m{m}={tab[m][(f,s)]}" for m in range(4)))

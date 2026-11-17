import sqlite3, json, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro&immutable=1", uri=True)
row = con.execute("select key, payload, result from jobs where task='size' and method='svgx' and split='confirmation' and result like '%\"branch\": \"structured\"%' limit 1").fetchone()
if row is None:
    row = con.execute("select key, payload, result from jobs where task='size' and method='svgx' and split='confirmation' limit 1").fetchone()
print("KEY", row[0]); print("PAYLOAD", row[1][:600])
r = json.loads(row[2])
def trunc(o, d=0):
    if isinstance(o, dict): return {k: trunc(v, d+1) for k, v in o.items()}
    if isinstance(o, list): return [trunc(v, d+1) for v in o[:3]] + (["...%d" % len(o)] if len(o) > 3 else [])
    if isinstance(o, str) and len(o) > 80: return o[:80] + "..."
    return o
print(json.dumps(trunc(r), indent=1)[:6000])
for m in ("brotli11", "xwrt_l6"):
    rr = con.execute("select result from jobs where task='size' and method=? limit 1", (m,)).fetchone()
    print(m, rr[0][:700])
t = con.execute("select key, payload, result from jobs where task='timing' and method='svgx_G' limit 2").fetchall()
for k, p, res in t: print("TIMING", k, p[:400], res[:600])

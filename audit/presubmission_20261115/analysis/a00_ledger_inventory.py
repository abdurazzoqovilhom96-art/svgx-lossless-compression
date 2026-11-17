import sqlite3, json, sys, collections
db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
cur = con.cursor()
print("tables:", [r[0] for r in cur.execute("select name from sqlite_master where type='table'")])
c = collections.Counter()
for split, task, method, status in cur.execute("select split, task, method, status from jobs"):
    c[(task, split, method, status)] += 1
for k in sorted(c): print(k, c[k])
print("attempts by status:", dict(cur.execute("select status, count(*) from attempts group by status").fetchall()))
print("events:", cur.execute("select utc, kind, detail from events").fetchall())
print("pauses:", cur.execute("select * from pauses").fetchall())
print("build_ids:", cur.execute("select build_id, count(*) from jobs group by build_id").fetchall())

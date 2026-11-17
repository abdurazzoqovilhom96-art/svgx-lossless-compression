"""Deduplicate, group provenance, assign splits and select the frozen pilot/confirmation manifests.

    python datasets/split.py            # reads data/candidates.csv, writes data/manifests/*.csv

Selection uses only input metadata and content signatures (never compression outcomes).
Statistical provenance family = union-find component of: creator family, declared lineage
(forks/derivatives), identical normalized content, shared path-data (Jaccard >= threshold) and
identical Commons title stems. A component lies entirely in one split.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.common import atomic_write_json, atomic_write_text, sha256_file, study_config  # noqa: E402

DATA = ROOT / "data"
FILES = DATA / "cache" / "files"
ORIG = DATA / "originals"
MAN = DATA / "manifests"
D_RX = re.compile(rb'\sd\s*=\s*("([^"]*)"|\'([^\']*)\')')


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            self.p[rb] = ra


def h(s: str, salt: str) -> str:
    return hashlib.sha256((salt + "\0" + s).encode()).hexdigest()


def normalized_hash(b: bytes) -> str:
    t = re.sub(rb"<!--.*?-->", b"", b, flags=re.S)
    t = re.sub(rb'\s(id|inkscape:[\w-]+|sodipodi:[\w-]+|data-name)\s*=\s*("[^"]*"|\'[^\']*\')', b"", t)
    t = re.sub(rb"<metadata.*?</metadata>", b"", t, flags=re.S | re.I)
    t = re.sub(rb"\s+", b" ", t).strip().lower()
    return hashlib.sha256(t).hexdigest()


def d_hashes(b: bytes) -> set[str]:
    out = set()
    for m in D_RX.finditer(b):
        v = m.group(2) if m.group(2) is not None else m.group(3)
        v = re.sub(rb"[\s,]+", b" ", v).strip()
        if len(v) >= 16:
            out.add(hashlib.sha1(v).hexdigest())
    return out


def title_stem(title: str) -> str:
    t = title.lower()
    t = re.sub(r"^file:", "", t)
    t = re.sub(r"\.svg$", "", t)
    t = re.sub(r"\((\w{2,3}|\d{4})\)", " ", t)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)
    t = re.sub(r"\b(v|ver|version)\s*\d+\b", " ", t)
    t = re.sub(r"[-_ ](en|de|fr|es|it|ru|uk|pl|pt|nl|ja|zh|ar|blank|new|old|updated|alt|\d+)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    atomic_write_text(path, buf.getvalue())


def main() -> int:
    cfg = study_config()
    cc = cfg["corpus"]
    seed = cc["selection_seed"]
    cats = cc["categories"]
    quotas = {"pilot": int(cc["pilot_per_category"]), "confirmation": int(cc["confirmation_per_category"])}
    caps = {s: max(1, int(round(q * float(cc["family_cap_fraction"])))) for s, q in quotas.items()}
    jac = float(cc["near_duplicate_jaccard"])
    recent = cc["confirmation_min_date"]
    cands = read_csv(DATA / "candidates.csv")
    # deterministic candidate order
    cands.sort(key=lambda r: (r["source_id"], r["path"], r["sha256"]))
    dedup = []
    first = {}
    files = []
    for r in cands:
        if r["category"] not in cats:
            continue
        if r["sha256"] in first:
            dedup.append({"sha256": r["sha256"], "title": r["title"], "source_id": r["source_id"], "decision": "removed",
                          "reason": "exact_duplicate", "linked_to": first[r["sha256"]]["title"], "group": ""})
            continue
        first[r["sha256"]] = r
        files.append(r)
    uf = UF()
    by_norm = {}
    dsets = {}
    inverted = defaultdict(list)
    for r in files:
        k = r["sha256"]
        uf.find(k)
        uf.union(k, "fam:" + r["family"])
        if r.get("lineage"):
            uf.union("fam:" + r["family"], "lin:" + r["lineage"])
        b = (FILES / f"{k}.svg").read_bytes()
        nh = normalized_hash(b)
        if nh in by_norm:
            uf.union(k, by_norm[nh])
            dedup.append({"sha256": k, "title": r["title"], "source_id": r["source_id"], "decision": "grouped",
                          "reason": "normalized_content_equal", "linked_to": first[by_norm[nh]]["title"], "group": ""})
        else:
            by_norm[nh] = k
        ds = d_hashes(b)
        dsets[k] = ds
        for x in ds:
            inverted[x].append(k)
    # shared path data (ignore ubiquitous shapes)
    pairs = set()
    for x, ks in inverted.items():
        if 2 <= len(ks) <= 50:
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    pairs.add((ks[i], ks[j]))
    for a, b2 in sorted(pairs):
        A, B = dsets[a], dsets[b2]
        if min(len(A), len(B)) >= 3 and len(A & B) / len(A | B) >= jac:
            if uf.find(a) != uf.find(b2):
                dedup.append({"sha256": b2, "title": first[b2]["title"], "source_id": first[b2]["source_id"],
                              "decision": "grouped", "reason": f"path_data_jaccard>={jac}", "linked_to": first[a]["title"], "group": ""})
            uf.union(a, b2)
    stems = {}
    for r in files:
        if r["source_id"].startswith("commons:"):
            st = r["category"] + "|" + title_stem(r["title"])
            if len(st) > len(r["category"]) + 4:
                if st in stems and uf.find(stems[st]) != uf.find(r["sha256"]):
                    dedup.append({"sha256": r["sha256"], "title": r["title"], "source_id": r["source_id"], "decision": "grouped",
                                  "reason": "title_stem_equal", "linked_to": first[stems[st]]["title"], "group": ""})
                    uf.union(stems[st], r["sha256"])
                stems.setdefault(st, r["sha256"])
    comp_of = {r["sha256"]: uf.find(r["sha256"]) for r in files}
    comp_id = {c: "grp-" + h(c, seed)[:12] for c in set(comp_of.values())}
    for r in files:
        r["group"] = comp_id[comp_of[r["sha256"]]]
    for d in dedup:
        d["group"] = comp_id.get(comp_of.get(d["sha256"], ""), "")
    comps = defaultdict(list)
    for r in files:
        comps[r["group"]].append(r)

    def contribution(rs, split, cat):
        by_f = defaultdict(int)
        for r in rs:
            if r["category"] == cat:
                by_f[r["group"]] += 1
        return sum(min(caps[split], n) for n in by_f.values())

    def is_recent(rs):
        ds = [r.get("original_date") or r.get("date") or "" for r in rs]
        return sum(1 for d in ds if d >= recent) * 2 >= len(ds)

    # Balanced assignment (decision D-13): a component goes to the split with the lower fill ratio
    # (capacity / quota) over its categories; recency only breaks ties (recent -> confirmation).
    order = sorted(comps, key=lambda g: h(g, seed + "/assign"))
    capacity = {s: {c: 0 for c in cats} for s in quotas}
    assign = {}
    for g in order:
        rs = comps[g]
        ccats = sorted({r["category"] for r in rs})
        # every component is assigned (breadth); the round-robin selection below spreads the quota
        # over all families of a split, and the cap only limits one family's share
        fill = {s: sum(capacity[s][c] / quotas[s] for c in ccats) / len(ccats) for s in quotas}
        if fill["pilot"] < fill["confirmation"]:
            target = "pilot"
        elif fill["confirmation"] < fill["pilot"]:
            target = "confirmation"
        else:
            target = "confirmation" if is_recent(rs) else "pilot"
        assign[g] = target
        for c in cats:
            capacity[target][c] += contribution(rs, target, c)
    # select files: per category round-robin over families (seeded), at most `cap` per family
    selected = {s: [] for s in quotas}
    shortfall = {}
    for s in quotas:
        for c in cats:
            fams = defaultdict(list)
            for g, sp in assign.items():
                if sp != s:
                    continue
                for r in comps[g]:
                    if r["category"] == c:
                        fams[g].append(r)
            for g in fams:
                fams[g].sort(key=lambda r: h(r["sha256"], seed + "/file"))
                fams[g] = fams[g][:caps[s]]
            keys = sorted(fams, key=lambda g: h(g, seed + "/rr/" + c))
            chosen, i = [], 0
            while len(chosen) < quotas[s] and any(fams[g] for g in keys):
                g = keys[i % len(keys)]
                if fams[g]:
                    chosen.append(fams[g].pop(0))
                i += 1
            selected[s] += chosen
            if len(chosen) < quotas[s]:
                shortfall[f"{s}/{c}"] = {"quota": quotas[s], "available": len(chosen)}
    ORIG.mkdir(parents=True, exist_ok=True)
    cols = ["file_id", "sha256", "size", "category", "family", "creator_family", "lineage", "creator", "license",
            "source_id", "revision", "url", "path", "date", "original_date", "title", "original"]
    summary = {"design_id": cfg["design"]["id"], "seed": seed, "quotas": quotas, "family_caps": caps,
               "candidates": len(cands), "unique": len(files), "components": len(comps), "splits": {}, "shortfall": shortfall}
    sel_keys = {}
    for s, rows in selected.items():
        out = []
        for r in sorted(rows, key=lambda r: (r["category"], r["group"], r["sha256"])):
            dst = ORIG / f"{r['sha256']}.svg"
            if not dst.exists():
                shutil.copyfile(FILES / f"{r['sha256']}.svg", dst)
            if sha256_file(dst) != r["sha256"]:
                raise RuntimeError(f"hash mismatch after copy: {dst}")
            out.append({**r, "file_id": f"{s[0].upper()}-{r['category'][:3]}-{r['sha256'][:12]}", "family": r["group"],
                        "creator_family": r["family"], "original": f"data/originals/{r['sha256']}.svg"})
            sel_keys[r["sha256"]] = s
        write_csv(MAN / f"{s}.csv", out, cols)
        per_cat = {c: sum(1 for r in out if r["category"] == c) for c in cats}
        fams_cat = {c: len({r["family"] for r in out if r["category"] == c}) for c in cats}
        summary["splits"][s] = {"files": len(out), "per_category": per_cat, "families": len({r["family"] for r in out}),
                                "families_per_category": fams_cat,
                                "creator_families": len({r["creator_family"] for r in out}),
                                "bytes": sum(int(r["size"]) for r in out)}
    for r in files:
        dedup.append({"sha256": r["sha256"], "title": r["title"], "source_id": r["source_id"],
                      "decision": "selected:" + sel_keys[r["sha256"]] if r["sha256"] in sel_keys else
                      ("unused_component" if assign.get(r["group"]) == "unused" else "not_selected"),
                      "reason": "selection", "linked_to": "", "group": r["group"]})
    write_csv(MAN / "dedup.csv", dedup, ["sha256", "title", "source_id", "decision", "reason", "linked_to", "group"])
    overlap = set(r["family"] for r in selected["pilot"]) & set(r["family"] for r in selected["confirmation"])
    summary["cross_split_family_overlap"] = len(overlap)
    summary["design_label"] = "full-quota" if not shortfall else "reduced (quotas infeasible; actual counts frozen)"
    atomic_write_json(MAN / "design.json", summary)
    print(f"pilot: {summary['splits']['pilot']['files']} fayl, tasdiq: {summary['splits']['confirmation']['files']} fayl; "
          f"komponentlar: {len(comps)}; yetishmovchilik: {shortfall or 'yo‘q'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

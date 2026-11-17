"""Select the example file by a fixed rule (read-only): confirmation split, the G output used the structured
stream, licence public domain, CC0 or CC BY (no SA/NC/ND), most modelled blocks.
Usage: python -I analysis/example_file/select_example.py <repo_root>"""
import csv, re, sys
from pathlib import Path

root = Path(sys.argv[1])
per = {r["file_id"]: r for r in csv.DictReader(open(root / "results/20261114_050438_SVGX-2026-11-A/03_raw/confirmation_per_file.csv", encoding="utf-8"))}
man = {r["file_id"]: r for r in csv.DictReader(open(root / "data/manifests/confirmation.csv", encoding="utf-8"))}
ok = re.compile(r"^(CC0|CC BY( \d\.\d)?|CC-BY(-\d\.\d)?|Public domain|PD)$", re.I)
cand = sorted(((int(r["blocks"] or 0), fid) for fid, r in per.items()
               if r["branch_G"] == "structured" and ok.match(man[fid]["license"].strip())), reverse=True)
blocks, fid = cand[0]
m = man[fid]
print(fid, blocks, "blocks |", m["title"], "|", m["license"], "|", m["sha256"], "|", m["url"])

"""Byte-exact round-trip check for SVGX.

For every input file and every spelling variant (D, P, I, U, G) the script
  1. encodes with `svgx encode --profile X` (the shipped output C = min(B, S)),
  2. also writes the forced structured stream (`--force-structured`) when the file has a modelled block,
  3. decodes each stream with the native decoder (`svgx decode`) and with the independent Python
     reference decoder (`reference/decode.py`),
  4. compares the SHA-256 of every restored file with the SHA-256 of the original bytes.
Optionally (--compare-with OTHER_SVGX) it checks that a second svgx binary writes byte-identical streams.

Usage:
  python -I analysis/roundtrip_check.py --svgx codec/target/release/svgx[.exe] FILE_OR_DIR [...]
         [--compare-with path/to/other/svgx] [--json report.json]
Exit code 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ["D", "P", "I", "U", "G"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--svgx", required=True)
    ap.add_argument("--compare-with")
    ap.add_argument("--json")
    ap.add_argument("inputs", nargs="+")
    a = ap.parse_args()
    files = []
    for x in a.inputs:
        p = Path(x)
        files += sorted(q for q in p.rglob("*.svg")) if p.is_dir() else [p]
    ref = ROOT / "reference" / "decode.py"
    rows, bad = [], 0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for f in files:
            orig = sha(f)
            for prof in PROFILES:
                for forced in (False, True):
                    out = td / f"{f.stem}.{prof}{'.forced' if forced else ''}.svgx"
                    cmd = [a.svgx, "encode", "--profile", prof] + (["--force-structured"] if forced else []) + [f, out]
                    r = run(cmd)
                    if r.returncode != 0:
                        if forced:  # no modelled block: no structured stream exists
                            continue
                        rows.append({"file": f.name, "profile": prof, "forced": forced, "ok": False, "error": r.stderr.decode(errors="replace")[:200]})
                        bad += 1
                        continue
                    nat, py = td / "nat.out", td / "py.out"
                    rn = run([a.svgx, "decode", out, nat])
                    rp = run([sys.executable, "-I", ref, out, py])
                    ok_n = rn.returncode == 0 and sha(nat) == orig
                    ok_p = rp.returncode == 0 and sha(py) == orig
                    same = None
                    if a.compare_with:
                        out2 = td / "other.svgx"
                        r2 = run([a.compare_with, "encode", "--profile", prof] + (["--force-structured"] if forced else []) + [f, out2])
                        same = r2.returncode == 0 and out2.read_bytes() == out.read_bytes()
                    ok = ok_n and ok_p and (same is not False)
                    bad += not ok
                    rows.append({"file": f.name, "bytes": f.stat().st_size, "profile": prof, "forced": forced,
                                 "stream_bytes": out.stat().st_size, "first_byte": f"0x{out.read_bytes()[0]:02x}",
                                 "native_ok": ok_n, "reference_ok": ok_p, "same_stream_as_other_binary": same, "ok": ok})
    n_struct = sum(1 for r in rows if r.get("first_byte") == "0x11")
    summary = {"files": len(files), "streams_checked": len(rows), "structured_streams": n_struct,
               "failures": bad, "all_ok": bad == 0}
    print(json.dumps(summary, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

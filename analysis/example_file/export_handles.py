"""Export the junctions, predicted handles and decoded handles of every block of one file.

The file is encoded with the svgx binary (variant G) and decoded by a temporary copy of reference/decode.py into
which two logging statements are inserted; reference/decode.py itself is not modified. The decoded bytes must equal
the original file. Usage:
  python -I analysis/example_file/export_handles.py <repo_root> <svgx.exe> <original.svg> <out.csv>
"""
import csv, hashlib, importlib.util, subprocess, sys, tempfile
from pathlib import Path

root, svgx, src, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
code = (root / "reference" / "decode.py").read_text(encoding="utf-8")
edits = [
    ("def need(cond: bool, msg: str) -> None:", "LOG, KS = [], []\n\n\ndef need(cond: bool, msg: str) -> None:"),
    ("            h1 = (ph1[0] + read_scalar(bits, p), ph1[1] + read_scalar(bits, p))\n",
     "            h1 = (ph1[0] + read_scalar(bits, p), ph1[1] + read_scalar(bits, p))\n"
     "            LOG.append((idx, mode, s, J[s], J[s + 1], ph0, h0, ph1, h1, dist if mode == 3 else 0))\n"),
    ("            junctions.append(J)\n", "            junctions.append(J)\n            KS.append(K)\n"),
]
for old, new in edits:
    assert code.count(old) == 1, old
    code = code.replace(old, new)
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    (td / "decode_logged.py").write_text(code, encoding="utf-8")
    enc = td / "file.svgx"
    subprocess.run([svgx, "encode", "--profile", "G", str(src), str(enc)], check=True)
    spec = importlib.util.spec_from_file_location("decode_logged", td / "decode_logged.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    orig = src.read_bytes()
    dec = m.decode_bytes(enc.read_bytes())
    assert dec == orig, "decoded bytes differ from the original"
    print("G stream", enc.stat().st_size, "bytes; decoded file identical, sha256", hashlib.sha256(dec).hexdigest())
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["block", "K", "mode", "ref_dist", "seg", "j0x", "j0y", "j1x", "j1y", "ph0x", "ph0y", "h0x", "h0y", "ph1x", "ph1y", "h1x", "h1y"])
    for idx, mode, s, a, b, ph0, h0, ph1, h1, dist in m.LOG:
        w.writerow([idx, m.KS[idx], mode, dist, s, *a, *b, *ph0, *h0, *ph1, *h1])
print("blocks", len(m.KS), "segments", len(m.LOG), "->", out)

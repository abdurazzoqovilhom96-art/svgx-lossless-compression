"""Deterministic synthetic SVG fixtures and their golden SVGX streams.

    python tools/fixtures.py generate   # (re)write fixtures/synthetic/svg/*.svg and golden streams
    python tools/fixtures.py check      # verify golden streams, hashes and both decoders

All outputs are SYNTHETIC test material, kept under fixtures/synthetic/.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.common import CODEC_BIN, FIXTURES, atomic_write_json, sha256_bytes, sha256_file  # noqa: E402

SVG_DIR = FIXTURES / "svg"
STREAMS = FIXTURES / "streams"
EXPECTED = FIXTURES / "expected.json"
PROFILES = ["D", "P", "I", "U", "G"]
NS = 'xmlns="http://www.w3.org/2000/svg"'


def svg(body: str, extra: str = "", decl: str = '<?xml version="1.0" encoding="UTF-8"?>\n') -> bytes:
    return (decl + f'<svg {NS} viewBox="0 0 100 100"{extra}>\n{body}\n</svg>\n').encode("utf-8")


def path(d: str, attrs: str = "") -> str:
    return f'  <path{attrs} d="{d}"/>'


def fmt(v: float, style: str) -> str:
    if style == "int":
        return str(int(round(v)))
    if style == "fixed2":
        return f"{v:.2f}"
    if style == "fixed3":
        return f"{v:.3f}"
    if style == "short3":
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    if style == "nolead":
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        if s in ("-0", ""):
            return "0"
        return s.replace("0.", ".", 1) if s.startswith(("0.", "-0.")) else s
    if style == "exp":
        return f"{v:.3e}"
    raise ValueError(style)


def curve_path(rng: random.Random, n_groups: int, style: str, rel: bool, compact: bool) -> str:
    x, y = rng.uniform(0, 100), rng.uniform(0, 100)
    parts = [f"M{fmt(x, style)},{fmt(y, style)}"]
    cmd = "c" if rel else "C"
    groups = []
    flat: list[str] = []
    for _ in range(n_groups):
        dx, dy = rng.uniform(-20, 20), rng.uniform(-20, 20)
        ex, ey = x + dx, y + dy
        c1 = (x + dx / 3 + rng.uniform(-2, 2), y + dy / 3 + rng.uniform(-2, 2))
        c2 = (x + 2 * dx / 3 + rng.uniform(-2, 2), y + 2 * dy / 3 + rng.uniform(-2, 2))
        pts = [c1, c2, (ex, ey)]
        if rel:
            pts = [(px - x, py - y) for px, py in pts]
        toks = []
        for px, py in pts:
            toks += [fmt(px, style), fmt(py, style)]
        flat += toks
        groups.append(" ".join(toks))
        # follow the endpoint as written so that absolute bookkeeping matches the text
        x = float(fmt(ex, style)) if not rel else x + float(fmt(ex - x, style))
        y = float(fmt(ey, style)) if not rel else y + float(fmt(ey - y, style))
    if compact:
        body = flat[0]
        for prev, t in zip(flat, flat[1:]):
            glue = t.startswith("-") or (t.startswith(".") and "." in prev and "e" not in prev.lower())
            body += t if glue else "," + t
        parts.append(cmd + body)
    else:
        parts.append(cmd + " ".join(groups))
    return "".join(parts) + "z"


def hand_built() -> dict[str, bytes]:
    f: dict[str, bytes] = {}
    f["zero_length"] = b""
    run4 = "C1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24"
    f["basic_abs"] = svg(path("M0 0" + run4 + "Z"))
    # same numeric value 2.5 as an absolute C token and as a relative c offset with a different start
    f["same_value_abs_rel"] = svg(
        path("M0,0C2.5,1 3,2 4,4 5,5 6,6 7,7 8,8 9,9 10,10 11,11 12,12 13,13") + "\n"
        + path("M10,10c2.5,1 3,2 4,4 1,1 2,2 3,3 1,1 2,2 3,3 1,1 2,2 3,3"))
    f["signed_zero"] = svg(path("M0 0C-0 0 +0 -0.0 1 1 -0 -0 0.0 +0.0 2 2 0 -0 -0 0 3 3 -0.00 0 0 -0 4 4"))
    f["exponents"] = svg(path("M0 0C1e-005 +5E-01 2.5e+0 1E1 3 3 1e+001 2e-1 4E-0 .5e1 5 5 6e0 7 8 9 10 10 1E-2 0 0 1 2 2"))
    f["dots"] = svg(path("M0 0C.5 5. -.5 0.50 1 1 00.5 1.50 2. .25 3 3 -1. -.75 4.0 4.00 5 5 .5 .5 6 6 7 7"))
    f["divergent_spellings"] = svg(path("M0 0C.5 0.5 0.50 +.5 1 1 .5 0.5 0.50 +0.5 2 2 0.500 .50 5e-1 +.5 3 3 .5 .5 .5 .5 4 4"))
    f["singular_anchor"] = svg(
        path("M0 0C1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0 11 0 12 0") + "\n"
        + path("M5 5C5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5") + "\n"
        + path("M0 0C1 1 2 2 3 3 1 2 3 4 3 3 0 0 1 1 3 3 2 2 1 1 3 3"))
    f["no_paths"] = svg('  <rect x="1" y="2" width="3" height="4"/>')
    f["no_namespace"] = b'<svg viewBox="0 0 10 10"><path d="M0 0' + run4.encode() + b'"/></svg>\n'
    f["prefixed_namespace"] = (b'<s:svg xmlns:s="http://www.w3.org/2000/svg"><s:path d="M0 0' + run4.encode()
                               + b'"/><path d="M0 0' + run4.encode() + b'"/></s:svg>\n')
    f["foreign_namespace"] = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="urn:other"><x:path d="M0 0'
                              + run4.encode() + b'"/><g xmlns="urn:other"><path d="M0 0' + run4.encode()
                              + b'"/></g></svg>\n')
    payload = bytes(range(256)).replace(b"<", b"").replace(b"&", b"").replace(b'"', b"").replace(b"-", b"")
    f["binary_latin1"] = (b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<svg ' + NS.encode() + b'>\n<!-- '
                          + payload + b' -->\n<image href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="/>\n'
                          + b'<path d="M0 0' + run4.encode() + b'"/>\n</svg>\n')
    f["non_utf8_undeclared"] = b'<svg ' + NS.encode() + b'><!-- \xff\xfe\x80 --><path d="M0 0' + run4.encode() + b'"/></svg>'
    f["utf16"] = '﻿<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0C1 2 3 4 5 6"/></svg>'.encode("utf-16-le")
    f["entity_path"] = svg(path("M0&#x20;0" + run4) + "\n" + path("M0 0" + run4))
    f["doctype_entity"] = (b'<?xml version="1.0"?>\n<!DOCTYPE svg [<!ENTITY e "M0 0">]>\n<svg ' + NS.encode()
                           + b'><path d="M0 0' + run4.encode() + b'"/></svg>\n')
    f["doctype_external"] = (b'<?xml version="1.0"?>\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                             b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<svg ' + NS.encode()
                             + b'><path d="M0 0' + run4.encode() + b'"/></svg>\n')
    f["malformed"] = b'<svg ' + NS.encode() + b'><path d="M0 0' + run4.encode() + b'"/>'
    f["compact_tokens"] = svg(path("M0 0c.5.5.5.5 1 1-.5-.5-.5-.5-1-1 .25.25.25.25 1 1-1.5.5-1.5.5-1 1z"))
    f["arcs_mixed"] = svg(path(
        "m10 10 5 5h3v-2a2 2 0 0 1 4 4l1 1s1 2 3 4q1 1 2 2t3 3"
        "c1 1 2 2 3 3 1 1 2 2 3 3 1 1 2 2 3 3 1 1 2 2 3 3zm1 1"
        "C1 1 2 2 3 3 4 4 5 5 6 6 7 7 8 8 9 9 10 10 11 11 12 12 13 13 14 14 15 15"
        "c1 2 3 4 5 6 1 2 3 4 5 6 1 2 3 4 5 6Z"
        "L0 0c1 1 2 2 3 3 1 1 2 2 3 3 1 1 2 2 3 3 1 1 2 2 3 3"))
    f["oversized_exponent"] = svg(path("M0 0C1e19 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24") + "\n"
                                  + path("M0 0C0.0000000000000000001 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24"))
    return f


def generated() -> dict[str, bytes]:
    f: dict[str, bytes] = {}
    styles = [("inkscape_like", "short3", True, False), ("illustrator_like", "nolead", True, True),
              ("fixed2_abs", "fixed2", False, False), ("int_abs", "int", False, False),
              ("fixed3_rel", "fixed3", True, False), ("exp_style", "exp", False, False)]
    for i, (name, style, rel, compact) in enumerate(styles):
        rng = random.Random(1000 + i)
        body = "\n".join(path(curve_path(rng, rng.randint(4, 40), style, rel, compact)) for _ in range(6))
        f[f"gen_{name}"] = svg(body)
    # curve-heavy regular file where the structured branch should win
    rng = random.Random(77)
    f["gen_structured_wins"] = svg("\n".join(path(curve_path(rng, 64, "fixed2", True, False)) for _ in range(30)))
    # > 4096 blocks (window bound) and > 16384 weight updates per role (rescaling)
    rng = random.Random(4242)
    f["gen_large_window_rescale"] = svg("\n".join(path(curve_path(rng, 4 * 700, "short3", True, False)) for _ in range(6)))
    return f


def all_fixtures() -> dict[str, bytes]:
    out = hand_built()
    out.update(generated())
    return out


def encode_all(src: Path, dst: Path) -> dict:
    if dst.exists():
        shutil.rmtree(dst)
    subprocess.run([str(CODEC_BIN), "encode-all", str(src), str(dst)], check=True)
    return json.loads((dst / "stats.json").read_text(encoding="utf-8"))


def generate() -> None:
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    for p in SVG_DIR.glob("*.svg"):
        p.unlink()
    expected = {"note": "SYNTHETIC fixtures generated by tools/fixtures.py; golden streams from svgx encode-all.",
                "codec": subprocess.run([str(CODEC_BIN), "--version"], capture_output=True, text=True).stdout.strip(),
                "files": {}}
    for name, data in sorted(all_fixtures().items()):
        src = SVG_DIR / f"{name}.svg"
        src.write_bytes(data)
        st = encode_all(src, STREAMS / name)
        entry = {"svg_sha256": sha256_bytes(data), "svg_len": len(data), "eligible": st["eligible"],
                 "file_reason": st["file_reason"], "blocks": st["blocks"], "streams": {}}
        for f in sorted((STREAMS / name).iterdir()):
            if f.suffix in (".svgx", ".br"):
                entry["streams"][f.name] = {"sha256": sha256_file(f), "len": f.stat().st_size}
        expected["files"][name] = entry
    atomic_write_json(EXPECTED, expected)
    print(f"{len(expected['files'])} ta sun'iy fixture yozildi: {EXPECTED}")


def check() -> int:
    """Re-encode every fixture and compare with golden streams; decode with both decoders."""
    import tempfile
    sys.path.insert(0, str(ROOT / "reference"))
    import decode as ref  # noqa: E402

    exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        for name, entry in sorted(exp["files"].items()):
            src = SVG_DIR / f"{name}.svg"
            if sha256_file(src) != entry["svg_sha256"]:
                print(f"✗ {name}: SVG hash mismatch"); bad += 1; continue
            out = Path(td) / name
            encode_all(src, out)
            for fname, meta in entry["streams"].items():
                f = out / fname
                if sha256_file(f) != meta["sha256"]:
                    print(f"✗ {name}/{fname}: golden stream mismatch"); bad += 1; continue
                data = f.read_bytes()
                orig = src.read_bytes()
                if ref.decode_bytes(data) != orig:
                    print(f"✗ {name}/{fname}: reference decoder mismatch"); bad += 1
                dec = Path(td) / f"{name}.{fname}.dec"
                r = subprocess.run([str(CODEC_BIN), "decode", str(f), str(dec)], capture_output=True)
                if r.returncode != 0 or dec.read_bytes() != orig:
                    print(f"✗ {name}/{fname}: native decoder mismatch"); bad += 1
    print("fixture tekshiruvi: " + ("muvaffaqiyatli" if not bad else f"{bad} ta xato"))
    return 1 if bad else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "generate":
        generate()
    else:
        sys.exit(check())

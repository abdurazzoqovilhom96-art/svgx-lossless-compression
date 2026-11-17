"""Verification: isolated decoder checks, byte comparison, SHA-256, section reconciliation and the
accounting invariants (C <= B, O <= C, raw fallback == independent baseline)."""
from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import time
from pathlib import Path

from .common import CODEC_BIN, ROOT, VENV_PY

HEADER = struct.Struct("<4BQIIIIQIQIII")
SECTION_NAMES = ("literals", "schedule", "geometry", "spelling", "escapes")
REFERENCE = ROOT / "reference" / "decode.py"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_header(data: bytes) -> dict | None:
    if len(data) < 60 or data[0] != 0x11:
        return None
    f = HEADER.unpack_from(data, 0)
    keys = ("marker", "version", "profile", "flags", "source_length", "crc32", "literal_len", "schedule_len",
            "geometry_len", "geometry_bits", "spelling_len", "spelling_bits", "escape_len", "escape_count",
            "hole_count")
    return dict(zip(keys, f))


def sections(data: bytes) -> dict:
    """Section byte ranges and hashes of a structured stream, with exact reconciliation."""
    h = parse_header(data)
    if h is None:
        return {"structured": False}
    lens = [h["literal_len"], h["schedule_len"], h["geometry_len"], h["spelling_len"], h["escape_len"]]
    off = 60
    out = {"structured": True, "header": h, "header_len": 60, "sections": {}}
    for name, n in zip(SECTION_NAMES, lens):
        out["sections"][name] = {"len": n, "sha256": sha(data[off:off + n])}
        off += n
    out["reconciled"] = off == len(data)
    out["padding_ok"] = True
    for name, bits_key in (("geometry", "geometry_bits"), ("spelling", "spelling_bits")):
        n = out["sections"][name]["len"]
        bits = h[bits_key]
        if n != (bits + 7) // 8:
            out["padding_ok"] = False
    # H(0): header with style fields zeroed — length is fixed at 60 bytes
    out["H0_len"] = 60
    out["L_len"] = h["literal_len"] + h["schedule_len"]
    out["R_len"] = h["geometry_len"]
    return out


def native_decode(stream: Path, out: Path) -> dict:
    t0 = time.perf_counter()
    r = subprocess.run([str(CODEC_BIN), "decode", str(stream), str(out)], capture_output=True)
    dt = time.perf_counter() - t0
    res = {"returncode": r.returncode, "elapsed_s": dt, "stderr": r.stderr.decode("utf-8", "replace")[-300:]}
    if r.returncode == 0 and out.exists():
        res["sha256"] = sha(out.read_bytes())
    return res


def reference_decode(stream: Path, out: Path, python: str | None = None) -> dict:
    """Run the independent Python decoder in an isolated interpreter process (-I)."""
    py = python or (str(VENV_PY) if VENV_PY.exists() else "python")
    t0 = time.perf_counter()
    r = subprocess.run([py, "-I", str(REFERENCE), str(stream), str(out)], capture_output=True)
    dt = time.perf_counter() - t0
    res = {"returncode": r.returncode, "elapsed_s": dt, "stderr": r.stderr.decode("utf-8", "replace")[-300:]}
    if r.returncode == 0 and out.exists():
        res["sha256"] = sha(out.read_bytes())
    return res


def verify_project_stream(stream: Path, original: bytes, work: Path) -> dict:
    """Both decoders on one project stream; byte equality and hashes."""
    work.mkdir(parents=True, exist_ok=True)
    want = sha(original)
    n = native_decode(stream, work / (stream.name + ".native"))
    r = reference_decode(stream, work / (stream.name + ".ref"))
    res = {
        "stream": stream.name, "len": stream.stat().st_size, "sha256": sha(stream.read_bytes()),
        "native_ok": n["returncode"] == 0 and n.get("sha256") == want and (work / (stream.name + ".native")).read_bytes() == original,
        "native_sha256": n.get("sha256"), "native_error": n["stderr"] if n["returncode"] else "",
        "reference_ok": r["returncode"] == 0 and r.get("sha256") == want and (work / (stream.name + ".ref")).read_bytes() == original,
        "reference_sha256": r.get("sha256"), "reference_error": r["stderr"] if r["returncode"] else "",
        "reference_elapsed_s": r["elapsed_s"], "native_verify_elapsed_s": n["elapsed_s"],
    }
    for p in (work / (stream.name + ".native"), work / (stream.name + ".ref")):
        try:
            os.unlink(p)
        except OSError:
            pass
    return res


def invariants(final: bytes, baseline: bytes, forced: bytes | None) -> dict:
    """C <= B; raw fallback byte-equal to baseline; structured strictly smaller; O <= C."""
    c, b = len(final), len(baseline)
    res = {"C": c, "B": b, "C_le_B": c <= b}
    if final[:1] == b"\x11":
        res["branch"] = "structured"
        res["fallback_equal"] = None
        res["strict_when_structured"] = c < b
    else:
        res["branch"] = "raw"
        res["fallback_equal"] = final == baseline
        res["strict_when_structured"] = True
    if forced is not None:
        s = sections(forced)
        o = min(b, s["H0_len"] + s["L_len"] + s["R_len"])
        res["O"] = o
        res["forced_len"] = len(forced)
        res["forced_reconciled"] = s["reconciled"] and s["padding_ok"]
    else:
        res["O"] = b
        res["forced_len"] = None
        res["forced_reconciled"] = True
    res["O_le_C"] = res["O"] <= c
    res["ok"] = bool(res["C_le_B"] and res["strict_when_structured"] and res["O_le_C"] and res["forced_reconciled"]
                     and (res["fallback_equal"] in (None, True)))
    return res

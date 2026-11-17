"""paq8px v217 adapter for REV1 (official Windows x64 binary, SHA-256 checked in freeze.py).

compress:   paq8px -LEVEL input.svg out.paq      (cwd = private work dir; fixed member name)
decompress: paq8px -d out.paq restored.svg
Single-file mode stores no file name in the archive; every archive starts with the magic b"paq8px", so its
first byte (0x70) can never be the SVGX structured marker 0x11 (checked on every archive).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from common import PAQ_EXE, REV1

sys.path.insert(0, str(REV1))
from runner.measure import run_measured  # noqa: E402

MAGIC = b"paq8px"


def roundtrip(data: bytes, level: int, work: Path, timeout: float | None = None) -> dict:
    """Compress `data` with paq8px -level and decompress it again; returns sizes, measurements, checks."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "input.svg").write_bytes(data)
    c = run_measured([str(PAQ_EXE), f"-{level}", "input.svg", "out.paq"], str(work), timeout=timeout)
    res = {"level": level, "input_len": len(data), "compress": {k: c[k] for k in ("returncode", "elapsed_s", "peak_memory_bytes", "user_s", "timed_out")}}
    arc = work / "out.paq"
    if c["returncode"] != 0 or c["timed_out"] or not arc.exists():
        res.update(ok=False, error="compress failed: " + c["stderr_tail"][-200:])
        shutil.rmtree(work, ignore_errors=True)
        return res
    a = arc.read_bytes()
    res["len"] = len(a)
    res["magic_ok"] = a[:len(MAGIC)] == MAGIC and a[0] != 0x11
    (work / "input.svg").unlink()
    d = run_measured([str(PAQ_EXE), "-d", "out.paq", "restored.svg"], str(work), timeout=timeout)
    res["decompress"] = {k: d[k] for k in ("returncode", "elapsed_s", "peak_memory_bytes", "user_s", "timed_out")}
    out = work / "restored.svg"
    res["roundtrip_ok"] = d["returncode"] == 0 and not d["timed_out"] and out.exists() and out.read_bytes() == data
    res["ok"] = bool(res["roundtrip_ok"] and res["magic_ok"])
    shutil.rmtree(work, ignore_errors=True)
    return res

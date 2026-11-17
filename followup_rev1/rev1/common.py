"""REV1 shared paths, helpers and the approval gate.

Design SVGX-REV1 (see docs/PROTOCOL_REV1.md). The original run, the original corpus files and the original toolchain
are used READ-ONLY from D:/13.11.2026/SVG_EXPERIMENT; nothing there is written.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REV1 = Path(__file__).resolve().parent.parent
ORIG = Path(r"D:/13.11.2026/SVG_EXPERIMENT")
RUN_ID = "20261114_050438_SVGX-2026-11-A"
RUN = ORIG / "results" / RUN_ID
LEDGER = RUN / "ledger.sqlite"
ORIGINALS = ORIG                      # manifest column "original" is relative to this root
PY = ORIG / ".venv" / "Scripts" / "python.exe"
SVGX = REV1 / "codec" / "target" / "release" / "svgx.exe"
SVGX_FROZEN = ORIG / "codec" / "target" / "release" / "svgx.exe"
REF_DECODER = REV1 / "reference" / "decode.py"
BROTLI_EXE = ORIG / ".tools" / "bin" / "brotli.exe"
ZSTD_EXE = ORIG / ".tools" / "zstd" / "zstd-v1.5.7-win64" / "zstd.exe"
PAQ_EXE = REV1 / ".tools_rev1" / "paq8px_v217" / "x" / "paq8px.exe"
OUT = REV1 / "results_rev1"
STATE = REV1 / "state"
FREEZE = STATE / "freeze_rev1.json"
APPROVAL = STATE / "approval_rev1.json"
FROZEN_HASHES = {  # must be unchanged from the original freeze (checked by freeze.py and by R0)
    "reference/decode.py": "554defc78ab5cb481ae5beece2a2ad5babd366408cceb95c7e08bd2bf6bc1ceb",
    "frozen_svgx.exe": "07a6841cb83d8a038f143bf40c2abbd8f43d575202746a64de40d90c0a63c2e1",
    "ledger.sqlite": "514a47d86b7f7a59fb9d731244e9fcff1cd9b65f69eaf835f29a66a61b10a99a",
}
PROFILES = ["D", "P", "I", "U", "G"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def manifest(split: str) -> list[dict]:
    """Corpus manifest of a split (REV1 copy, byte-identical to the frozen one; checked in freeze.py)."""
    with open(REV1 / "data" / "manifests" / f"{split}.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["path"] = str(ORIGINALS / r["original"])
    return rows


def ledger_size_results(file_ids: set[str] | None = None) -> dict[str, dict]:
    """Per-file svgx size-job results of the frozen run, opened read-only."""
    con = sqlite3.connect("file:" + str(LEDGER).replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    out = {}
    for payload, res in con.execute("select payload, result from jobs where method='svgx' and task='size'"):
        fid = json.loads(payload)["file_id"]
        if file_ids is None or fid in file_ids:
            out[fid] = json.loads(res)
    con.close()
    return out


def ledger_comparator_sizes(method: str) -> dict[str, int]:
    con = sqlite3.connect("file:" + str(LEDGER).replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    out = {}
    for payload, res in con.execute("select payload, result from jobs where method=? and task='size'", (method,)):
        out[json.loads(payload)["file_id"]] = json.loads(res)["len"]
    con.close()
    return out


def run(argv, *, cwd=None, check=False, timeout=None) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True, timeout=timeout, check=check)


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    tmp.replace(p)


def require_approval(stage: str) -> dict:
    """Refuse to run an experiment stage on the confirmation split without a recorded approval that is bound to the
    SHA-256 of the current freeze record and whose scope includes `stage`. Exit code 4 otherwise."""
    if not FREEZE.exists():
        sys.exit(f"[REV1] {stage}: freeze record missing ({FREEZE}); nothing was run.")
    if not APPROVAL.exists():
        print(f"[REV1] {stage}: no approval record ({APPROVAL}); nothing was run.", file=sys.stderr)
        sys.exit(4)
    a = json.loads(APPROVAL.read_text(encoding="utf-8"))
    fz = sha256_file(FREEZE)
    if a.get("decision") != "approve" or a.get("freeze_sha256") != fz or stage not in a.get("scope", []):
        print(f"[REV1] {stage}: approval missing, declined, out of scope or bound to another freeze "
              f"(freeze {fz[:12]}…); nothing was run.", file=sys.stderr)
        sys.exit(4)
    return a


def svgx_raw_bytes(data: bytes, work: Path) -> bytes:
    """The codec's own Brotli (quality 11, lgwin 22) through `svgx raw` (identical library build)."""
    work.mkdir(parents=True, exist_ok=True)
    src, dst = work / "_raw_in.bin", work / "_raw_out.br"
    src.write_bytes(data)
    r = run([SVGX, "raw", src, dst])
    if r.returncode != 0:
        raise RuntimeError("svgx raw failed: " + r.stderr.decode("utf-8", "replace")[-300:])
    out = dst.read_bytes()
    src.unlink()
    dst.unlink()
    return out


def encode_all(src: Path, outdir: Path, modes: str | None = None, exe: Path = SVGX) -> dict:
    """`svgx encode-all [--modes L] src outdir`; returns the stream bytes and stats."""
    if outdir.exists():
        import shutil
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    argv = [exe, "encode-all"] + (["--modes", modes] if modes else []) + [src, outdir]
    r = run(argv)
    if r.returncode != 0:
        raise RuntimeError(f"encode-all {modes} failed on {src}: " + r.stderr.decode("utf-8", "replace")[-300:])
    res = {"raw": (outdir / "raw.br").read_bytes(), "stats": json.loads((outdir / "stats.json").read_text(encoding="utf-8")),
           "final": {}, "forced": {}}
    for p in PROFILES:
        res["final"][p] = (outdir / f"{p}.svgx").read_bytes()
        fp = outdir / f"{p}.forced.svgx"
        res["forced"][p] = fp.read_bytes() if fp.exists() else None
    return res


def verify_stream(stream: bytes, original: bytes, work: Path) -> dict:
    """Decode one SVGX stream with the native decoder (REV1 build) and with the frozen Python reference decoder
    (isolated interpreter, -I); both must restore the original bytes exactly."""
    work.mkdir(parents=True, exist_ok=True)
    s, n_out, r_out = work / "_v.svgx", work / "_v.native", work / "_v.ref"
    s.write_bytes(stream)
    n = run([SVGX, "decode", s, n_out])
    native_ok = n.returncode == 0 and n_out.exists() and n_out.read_bytes() == original
    r = run([PY, "-I", REF_DECODER, s, r_out])
    ref_ok = r.returncode == 0 and r_out.exists() and r_out.read_bytes() == original
    for p in (s, n_out, r_out):
        if p.exists():
            p.unlink()
    return {"native_ok": native_ok, "reference_ok": ref_ok,
            "native_error": "" if native_ok else n.stderr.decode("utf-8", "replace")[-300:],
            "reference_error": "" if ref_ok else r.stderr.decode("utf-8", "replace")[-300:]}


def append_jsonl(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def stage_split_guard(stage: str, split: str) -> None:
    """Pilot and synthetic fixtures may be processed during preparation; the confirmation split only with approval."""
    if split == "confirmation":
        require_approval(stage)
    elif split not in ("pilot", "fixtures"):
        sys.exit(f"unknown split {split}")


def check_frozen_inputs() -> dict:
    """Verify that the read-only inputs are the frozen ones (reference decoder, frozen binary, ledger)."""
    got = {"reference/decode.py": sha256_file(REF_DECODER), "frozen_svgx.exe": sha256_file(SVGX_FROZEN),
           "ledger.sqlite": sha256_file(LEDGER)}
    return {k: {"expected": FROZEN_HASHES[k], "actual": v, "ok": v == FROZEN_HASHES[k]} for k, v in got.items()}

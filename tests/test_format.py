"""Strict rejection, section reconciliation and common-section identity (FORMAT.md §1, §2, §11)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from conftest import SVG_DIR, svgx
from runner.verify import sections

SRC = SVG_DIR / "gen_structured_wins.svg"


@pytest.fixture(scope="module")
def streams(tmp_path_factory):
    out = tmp_path_factory.mktemp("fmt")
    svgx("encode-all", SRC, out)
    return out


def both_reject(data: bytes, tmp: Path, ref):
    f = tmp / "bad.bin"
    f.write_bytes(data)
    r = svgx("decode", f, tmp / "bad.out", check=False)
    assert r.returncode == 4, f"native accepted invalid stream ({r.returncode})"
    with pytest.raises(ref.FormatError):
        ref.decode_bytes(data)


def test_empty_and_0x91(tmp_path, ref):
    both_reject(b"", tmp_path, ref)
    both_reject(b"\x91" + b"\x00" * 10, tmp_path, ref)


def test_raw_brotli_strict(streams, tmp_path, ref):
    raw = (streams / "raw.br").read_bytes()
    both_reject(raw + b"\x00", tmp_path, ref)
    both_reject(raw[:-1], tmp_path, ref)


@pytest.mark.parametrize("profile", ["D", "P", "I", "U", "G"])
def test_structured_mutations(streams, tmp_path, ref, profile):
    data = (streams / f"{profile}.forced.svgx").read_bytes()
    both_reject(data[:-1], tmp_path, ref)                       # truncation
    both_reject(data + b"\x00", tmp_path, ref)                  # trailing byte
    for off, val in ((1, 2), (2, 9), (3, 1)):                   # version, profile, flags
        m = bytearray(data)
        m[off] = val
        both_reject(bytes(m), tmp_path, ref)
    m = bytearray(data)
    struct.pack_into("<I", m, 12, struct.unpack_from("<I", m, 12)[0] ^ 1)   # CRC mismatch
    both_reject(bytes(m), tmp_path, ref)
    m = bytearray(data)
    struct.pack_into("<I", m, 16, struct.unpack_from("<I", m, 16)[0] + 1)   # malformed section length
    both_reject(bytes(m), tmp_path, ref)
    m = bytearray(data)
    struct.pack_into("<Q", m, 28, struct.unpack_from("<Q", m, 28)[0] + 1)   # geometry bit count
    both_reject(bytes(m), tmp_path, ref)
    m = bytearray(data)
    struct.pack_into("<I", m, 56, struct.unpack_from("<I", m, 56)[0] + 16)  # hole count
    both_reject(bytes(m), tmp_path, ref)


def test_reconciliation_and_common_sections(streams):
    secs = {p: sections((streams / f"{p}.forced.svgx").read_bytes()) for p in "DPIUG"}
    for p, s in secs.items():
        assert s["reconciled"] and s["padding_ok"], p
        assert s["H0_len"] == 60
    for name in ("literals", "schedule", "geometry"):
        assert len({s["sections"][name]["sha256"] for s in secs.values()}) == 1, name
    assert len({secs[p]["sections"]["escapes"]["sha256"] for p in "IUG"}) == 1
    assert secs["D"]["sections"]["spelling"]["len"] == 0
    assert secs["D"]["header"]["escape_count"] == secs["D"]["header"]["hole_count"]


def test_ceiling_bound(streams):
    st = json.loads((streams / "stats.json").read_text(encoding="utf-8"))
    o = st["style_free_ceiling_O"]
    for p, v in st["profiles"].items():
        assert o <= v["final_len"] <= st["raw_brotli_len"], p


def test_branch_marker_disjoint(streams):
    raw = (streams / "raw.br").read_bytes()
    assert raw[0] & 0x7F != 0x11

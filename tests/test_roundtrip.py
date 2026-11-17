"""encode → decode → compare for every model, both decoders, every fixture (incl. forced-structured)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import fixture_files, svgx

PROFILES = ["D", "P", "I", "U", "G"]


@pytest.mark.parametrize("src", fixture_files(), ids=lambda p: p.stem)
def test_encode_all_roundtrip(src: Path, tmp_path: Path, ref):
    out = tmp_path / "o"
    svgx("encode-all", src, out)
    orig = src.read_bytes()
    st = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    raw = (out / "raw.br").read_bytes()
    for p in PROFILES:
        for name in (f"{p}.svgx", f"{p}.forced.svgx"):
            f = out / name
            if not f.exists():
                assert name.endswith(".forced.svgx") and not st["eligible"]
                continue
            data = f.read_bytes()
            assert ref.decode_bytes(data) == orig, f"reference decoder: {name}"
            d = tmp_path / (name + ".dec")
            svgx("decode", f, d)
            assert d.read_bytes() == orig, f"native decoder: {name}"
        final = (out / f"{p}.svgx").read_bytes()
        assert len(final) <= len(raw)
        if final[0] != 0x11:
            assert final == raw
    if st["eligible"]:
        assert (out / "G.forced.svgx").read_bytes()[0] == 0x11


@pytest.mark.parametrize("profile", PROFILES)
def test_standalone_forced_each_profile(profile, tmp_path: Path, ref):
    """Forced structured stream per profile through the standalone `encode` command."""
    src = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic" / "svg" / "gen_structured_wins.svg"
    s = tmp_path / "s.svgx"
    svgx("encode", "--profile", profile, "--force-structured", "--stats", tmp_path / "st.json", src, s)
    data = s.read_bytes()
    assert data[0] == 0x11 and data[2] == PROFILES.index(profile) + 1
    assert ref.decode_bytes(data) == src.read_bytes()
    svgx("decode", s, tmp_path / "d")
    assert (tmp_path / "d").read_bytes() == src.read_bytes()


def test_same_value_absolute_and_relative(tmp_path: Path, ref):
    """The same numeric value appears once as an absolute C token and once as a relative c offset."""
    src = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic" / "svg" / "same_value_abs_rel.svg"
    out = tmp_path / "o"
    svgx("encode-all", src, out)
    st = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    roles = {r["role"]: r["tokens"] for r in st["roles"]}
    assert roles[0] > 0 and roles[4] > 0  # absolute P1.x and relative P1.x roles both present
    assert ref.decode_bytes((out / "G.forced.svgx").read_bytes()) == src.read_bytes()


def test_zero_length_source(tmp_path: Path, ref):
    src = tmp_path / "empty.svg"
    src.write_bytes(b"")
    svgx("encode", "--profile", "G", src, tmp_path / "e.svgx")
    data = (tmp_path / "e.svgx").read_bytes()
    assert len(data) >= 1 and data[0] != 0x11
    assert ref.decode_bytes(data) == b""
    svgx("decode", tmp_path / "e.svgx", tmp_path / "e.out")
    assert (tmp_path / "e.out").read_bytes() == b""


def test_forced_without_blocks(tmp_path: Path, ref):
    """A forced structured stream of a file without modeled paths is still a valid, self-decodable stream."""
    src = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic" / "svg" / "no_paths.svg"
    svgx("encode", "--profile", "G", "--force-structured", src, tmp_path / "f.svgx")
    data = (tmp_path / "f.svgx").read_bytes()
    assert data[0] == 0x11
    assert ref.decode_bytes(data) == src.read_bytes()

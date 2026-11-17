"""Every available external comparator round-trips fixtures with its own pinned decoder."""
from __future__ import annotations

import pytest

from baselines.adapters import methods, roundtrip
from conftest import SVG_DIR

SAMPLES = ["gen_inkscape_like.svg", "binary_latin1.svg", "zero_length.svg", "utf16.svg"]


@pytest.mark.parametrize("name", sorted(methods()))
def test_method_roundtrip(name, tmp_path):
    m = methods()[name]
    ok, why = m.available()
    if not ok:
        pytest.skip(f"comparator missing: {why}")
    for s in SAMPLES:
        if m.tool == "xwrt" and s == "zero_length.svg":
            continue  # XWRT limitation on empty input is recorded in readiness, not hidden
        r = roundtrip(m, str(SVG_DIR / s), str(tmp_path / s))
        assert r["roundtrip_ok"], (name, s)


def test_primary_brotli_equals_codec_raw(tmp_path):
    import subprocess
    from runner.common import CODEC_BIN
    m = methods()["brotli11"]
    for s in SAMPLES:
        r = roundtrip(m, str(SVG_DIR / s), str(tmp_path / s))
        raw = tmp_path / (s + ".raw")
        subprocess.run([str(CODEC_BIN), "raw", str(SVG_DIR / s), str(raw)], check=True)
        stream = tmp_path / s / "brotli11.stream"
        assert stream.read_bytes() == raw.read_bytes(), s
        assert r["roundtrip_ok"]


def test_external_deterministic(tmp_path):
    for name in ("ppmd7z", "xz9e", "zstd19", "gzip9", "xwrt_l6"):
        m = methods()[name]
        if not m.available()[0]:
            continue
        a = roundtrip(m, str(SVG_DIR / "gen_fixed2_abs.svg"), str(tmp_path / "a"))
        b = roundtrip(m, str(SVG_DIR / "gen_fixed2_abs.svg"), str(tmp_path / "b"))
        assert a["stream_sha256"] == b["stream_sha256"], name

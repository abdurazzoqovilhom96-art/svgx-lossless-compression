"""REV1 tests: T/Z sections, restricted-mode CLI, analysis arithmetic and the approval gate (synthetic data only)."""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REV1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REV1 / "rev1"))
import common  # noqa: E402
import sections  # noqa: E402

FIX = REV1 / "fixtures" / "synthetic" / "svg"


# ------------------------------------------------------------------ bit coding
def test_bitwriter_reader_roundtrip():
    rnd = random.Random(1)
    w = sections.BitWriter()
    vals = []
    for _ in range(2000):
        n = rnd.randint(0, 70)
        v = rnd.getrandbits(n) if n else 0
        vals.append((v, n))
        w.put(v, n)
    data = w.to_bytes()
    r = sections.BitReader(data, w.nbits)
    assert [r.get(n) for _, n in vals] == [v for v, _ in vals]


def test_bitreader_rejects_nonzero_padding_and_overrun():
    with pytest.raises(AssertionError):
        sections.BitReader(b"\x01", 7)
    r = sections.BitReader(b"\x80", 1)
    assert r.get(1) == 1
    with pytest.raises(AssertionError):
        r.get(1)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_z_roundtrip_signed_and_huge(seed):
    rnd = random.Random(seed)
    vals = []
    for _ in range(16 * 40):
        kind = rnd.random()
        if kind < 0.3:
            vals.append(rnd.randint(-3, 3))
        elif kind < 0.9:
            vals.append(rnd.randint(-10 ** 6, 10 ** 6))
        else:
            vals.append(rnd.choice([-1, 1]) * rnd.getrandbits(95))
    data, bits = sections.z_encode(vals)
    assert len(data) == (bits + 7) // 8
    assert sections.z_decode(data, bits, len(vals)) == vals


def test_zigzag():
    for r in range(-1000, 1000):
        assert sections.unzig(sections.zig(r)) == r
    assert [sections.zig(x) for x in (0, -1, 1, -2, 2)] == [0, 1, 2, 3, 4]


def test_t_holes_text_rejects_space():
    with pytest.raises(AssertionError):
        sections.t_holes_text([b"1", b"2 3"])
    assert sections.t_holes_text([b"1", b"-2.5", b"3e1"]) == b"1 -2.5 3e1"


# ------------------------------------------------------------------ codec CLI and sections on fixtures
def _encode(args, src, dst):
    return subprocess.run([str(common.SVGX), "encode", "--profile", "G", "--force-structured", *args, str(src), str(dst)],
                          capture_output=True)


def test_modes_requires_00(tmp_path):
    for bad in ("01", "01,11", "02", "00,12"):
        r = _encode(["--modes", bad], FIX / "basic_abs.svg", tmp_path / "o")
        assert r.returncode == 2, bad


def test_default_equals_all_modes_and_frozen(tmp_path):
    f = FIX / "gen_structured_wins.svg"
    a, b = tmp_path / "a", tmp_path / "b"
    assert _encode([], f, a).returncode == 0
    assert _encode(["--modes", "00,01,10,11"], f, b).returncode == 0
    c = tmp_path / "c"
    subprocess.run([str(common.SVGX_FROZEN), "encode", "--profile", "G", "--force-structured", str(f), str(c)], check=True)
    assert a.read_bytes() == b.read_bytes() == c.read_bytes()


def test_tz_arms_on_fixture(tmp_path):
    f = FIX / "gen_structured_wins.svg"
    s = tmp_path / "s"
    assert _encode([], f, s).returncode == 0
    res = sections.tz_arms(s.read_bytes(), f.read_bytes(), lambda b: common.svgx_raw_bytes(b, tmp_path / "br"))
    assert res["T_roundtrip_ok"] and res["Z_roundtrip_ok"]
    assert res["S_T"] == 60 + res["literal_len"] + res["schedule_len"] + res["T_section_len"]
    assert res["S_Z"] == 60 + res["literal_len"] + res["schedule_len"] + res["Z_section_len"] + res["spelling_len_G"] + res["escape_len_G"]


# ------------------------------------------------------------------ analysis arithmetic
def _rows(n_fam=12, seed=3):
    rnd = random.Random(seed)
    rows = []
    for f in range(n_fam):
        for i in range(rnd.randint(1, 4)):
            B = rnd.randint(1000, 5000)
            cf = B - rnd.randint(0, 200)
            d0 = rnd.randint(cf, B)
            rows.append({"file_id": f"f{f}_{i}", "family": f"fam{f:02d}", "B": B, "C_F": cf, "C_D0": d0})
    return rows


def test_ratio_bootstrap_reproducible_and_bounded():
    import analysis
    est = {"R1": analysis.B1_EST["R1"]}
    rows = _rows()
    v = analysis.value(rows, est["R1"])
    assert 0 <= v <= 1
    b1 = analysis.boot(rows, est, 3000, 7)
    b2 = analysis.boot(rows, est, 3000, 7)
    assert np.array_equal(b1["draws"]["R1"], b2["draws"]["R1"])
    d = b1["draws"]["R1"][np.isfinite(b1["draws"]["R1"])]
    assert d.min() >= 0 and d.max() <= 1
    iv = analysis.intervals(v, b1["draws"]["R1"], b1["jack"]["R1"], 3, 0.995)
    assert iv["bonferroni"][0] <= iv["marginal"][0] <= v <= iv["marginal"][1] <= iv["bonferroni"][1]


def test_jackknife_is_leave_one_family_out():
    import analysis
    rows = _rows()
    est = analysis.B1_EST["R1"]
    b = analysis.boot(rows, {"R1": est}, 10, 1)
    fams = sorted({r["family"] for r in rows})
    for j, fam in enumerate(fams):
        assert b["jack"]["R1"][j] == pytest.approx(analysis.value([r for r in rows if r["family"] != fam], est))


def test_wording_rules():
    import analysis
    w = analysis.wording
    assert w("R1", 0.5, 0.9, 0.7).startswith("prediction is the main source")
    assert w("R1", 0.3, 0.9, 0.6).startswith("prediction contributes a substantial")
    assert w("R1", 0.1, 0.9, 0.2).startswith("prediction contributes a minor")
    assert w("R1", 0.0, 0.2, 0.05).startswith("the saving comes mainly")
    assert w("Gain_H", 0.005, 0.02, 0.01).startswith("geometric modelling retains")
    assert w("Gain_H", 0.004, 0.02, 0.01).startswith("no material gain")
    assert w("tau_dec", 0.5, 0.9, 0.7) == "faster"
    assert w("tau_dec", 1.1, 1.5, 1.3).startswith("slower")
    assert w("tau_dec", 0.9, 1.1, 1.0) == "comparable"


# ------------------------------------------------------------------ approval gate
def test_approval_gate(tmp_path, monkeypatch):
    fz, ap = tmp_path / "freeze.json", tmp_path / "approval.json"
    monkeypatch.setattr(common, "FREEZE", fz)
    monkeypatch.setattr(common, "APPROVAL", ap)
    with pytest.raises(SystemExit):
        common.require_approval("B1")                      # no freeze
    fz.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        common.require_approval("B1")                      # no approval
    assert e.value.code == 4
    good = {"decision": "approve", "scope": ["B1"], "freeze_sha256": common.sha256_file(fz)}
    for bad in (dict(good, decision="decline"), dict(good, scope=["B2"]), dict(good, freeze_sha256="0" * 64), {}):
        ap.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(SystemExit) as e:
            common.require_approval("B1")
        assert e.value.code == 4
    ap.write_text(json.dumps(good), encoding="utf-8")
    assert common.require_approval("B1")["decision"] == "approve"
    fz.write_text('{"changed": 1}', encoding="utf-8")       # re-freeze invalidates the approval
    with pytest.raises(SystemExit) as e:
        common.require_approval("B1")
    assert e.value.code == 4


def test_confirmation_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "FREEZE", tmp_path / "none.json")
    with pytest.raises(SystemExit):
        common.stage_split_guard("B1", "confirmation")
    common.stage_split_guard("B1", "pilot")                # allowed during preparation

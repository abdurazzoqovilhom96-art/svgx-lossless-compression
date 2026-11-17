"""Regression tests for the audit computations (A01, A02). Run: python -m pytest -q analysis/test_audit_regression.py"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("a07", HERE / "a07_completeness.py")
a07 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a07)


def wtl(rows, a, c):
    """Same definitions as a02_recompute.comp: win C<A, tie C==A, loss C>A on integer bytes; family = sign of net sum."""
    w = sum(1 for r in rows if r[c] < r[a])
    t = sum(1 for r in rows if r[c] == r[a])
    fam = {}
    for r in rows:
        fam[r["family"]] = fam.get(r["family"], 0) + r[a] - r[c]
    return (w, t, len(rows) - w - t), (sum(g > 0 for g in fam.values()), sum(g == 0 for g in fam.values()),
                                       sum(g < 0 for g in fam.values()))


def test_wtl_zero_and_negative():
    rows = [{"family": "f1", "A": 10, "C": 9}, {"family": "f1", "A": 10, "C": 12},   # family net -1 -> loss
            {"family": "f2", "A": 5, "C": 5},                                         # tie, no tolerance
            {"family": "f3", "A": 7, "C": 6}]
    files, fams = wtl(rows, "A", "C")
    assert files == (2, 1, 1)
    assert fams == (1, 1, 1)


def test_gain_uses_byte_totals_not_mean_of_percentages():
    rows = [{"A": 100, "C": 50}, {"A": 10000, "C": 10000}]
    pooled = 100 * (sum(r["A"] for r in rows) - sum(r["C"] for r in rows)) / sum(r["A"] for r in rows)
    mean_pct = sum(100 * (r["A"] - r["C"]) / r["A"] for r in rows) / len(rows)
    assert abs(pooled - 0.4950495) < 1e-6 and mean_pct == 25.0


def test_classifier_separates_not_scheduled_from_missing():
    assert a07.classify(None, scheduled=False) == "not_scheduled_by_design"
    assert a07.classify(None, scheduled=True) == "missing"
    assert a07.classify({"available": False}, scheduled=True) == "not_applicable"
    assert a07.classify({"available": True, "roundtrip_ok": False}, scheduled=True) == "failed"
    assert a07.classify({"available": True, "roundtrip_ok": True}, scheduled=True) == "measured"


def test_frozen_run_completeness_corrected():
    out = a07.main()
    for split, n in (("pilot", 248), ("confirmation", 1076)):
        c = out["corrected"][split]
        assert c["files_with_complete_paired_size_set"] == n
        assert c["missing_measurements_corrected"] == 0
        assert c["cells_by_status"]["not_scheduled_by_design"] == 2 * n
    assert out["original_report"]["pilot_missing_measurements"] == 496
    assert out["original_report"]["confirmation_missing_measurements"] == 2152


def test_recomputed_tables_match_report():
    chk = json.loads((HERE.parent / "derived" / "checks_a02.json").read_text(encoding="utf-8"))
    assert chk["report_vs_recomputed_differences"] == []
    assert chk["problem_count"] == 0
    assert chk["confirmation_restored_all_arms_both_decoders"] == 1076

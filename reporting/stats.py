"""Paired statistics on complete files (PROTOCOL.md §Statistics). Pure functions over row dicts."""
from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np


def _sum(rows, col):
    return sum(int(r[col]) for r in rows)


def gain(rows, a: str, c: str) -> float | None:
    """Gain(A, C) = 100 (sum A - sum C) / sum A on the same files; None if sum A = 0."""
    sa = _sum(rows, a)
    if sa <= 0:
        return None
    return 100.0 * (sa - _sum(rows, c)) / sa


def families(rows) -> OrderedDict:
    fam = OrderedDict()
    for r in sorted(rows, key=lambda r: (r["family"], r["file_id"])):
        fam.setdefault(r["family"], []).append(r)
    return fam


def family_outcomes(rows, a: str, c: str) -> dict:
    out = {"wins": 0, "ties": 0, "losses": 0, "per_family": {}}
    for f, rs in families(rows).items():
        g = sum(int(r[a]) - int(r[c]) for r in rs)
        out["per_family"][f] = {"g": g, "files": len(rs), "A": _sum(rs, a), "C": _sum(rs, c)}
        out["wins" if g > 0 else "ties" if g == 0 else "losses"] += 1
    out["m"] = len(out["per_family"])
    return out


def file_median_relative_gain(rows, a: str, c: str) -> float | None:
    vals = [100.0 * (int(r[a]) - int(r[c])) / int(r[a]) for r in rows if int(r[a]) > 0]
    return float(np.median(vals)) if vals else None


def strict_wins(rows, a: str, c: str) -> dict:
    w = sum(1 for r in rows if int(r[c]) < int(r[a]))
    t = sum(1 for r in rows if int(r[c]) == int(r[a]))
    return {"wins": w, "ties": t, "losses": len(rows) - w - t, "n": len(rows)}


def class_totals(rows, a: str, c: str) -> dict:
    out = {}
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        out[cat] = {"n": len(rs), "A": _sum(rs, a), "C": _sum(rs, c), "gain_percent": gain(rs, a, c)}
    return out


def equal_family_gain(rows, a: str, c: str) -> float | None:
    gs = [gain(rs, a, c) for rs in families(rows).values()]
    gs = [g for g in gs if g is not None]
    return float(np.mean(gs)) if gs else None


def leave_one_family_out(rows, a: str, c: str) -> dict:
    fam = families(rows)
    vals = {}
    for f in fam:
        rest = [r for g, rs in fam.items() if g != f for r in rs]
        vals[f] = gain(rest, a, c) if rest else None
    finite = [v for v in vals.values() if v is not None]
    return {"min": min(finite) if finite else None, "max": max(finite) if finite else None, "per_family": vals}


def dominance(rows, a: str) -> dict:
    fam = families(rows)
    tot = _sum(rows, a) or 1
    shares = sorted(((f, _sum(rs, a) / tot) for f, rs in fam.items()), key=lambda x: -x[1])
    return {"largest_family": shares[0][0] if shares else None, "largest_share": shares[0][1] if shares else None,
            "top3_share": sum(s for _, s in shares[:3])}


def summarize(rows, a: str, c: str) -> dict:
    fo = family_outcomes(rows, a, c)
    return {
        "A": a, "C": c, "n_files": len(rows), "sum_A": _sum(rows, a), "sum_C": _sum(rows, c),
        "gain_percent": gain(rows, a, c), "file_median_relative_gain_percent": file_median_relative_gain(rows, a, c),
        "file_strict": strict_wins(rows, a, c), "families": {k: fo[k] for k in ("wins", "ties", "losses", "m")},
        "equal_family_gain_percent": equal_family_gain(rows, a, c), "class_totals": class_totals(rows, a, c),
        "leave_one_family_out": {k: v for k, v in leave_one_family_out(rows, a, c).items() if k != "per_family"},
        "dominance": dominance(rows, a),
    }


def bootstrap(rows, contrasts: dict, *, resamples: int, seed: int, chunk: int = 2000) -> dict:
    """Paired family bootstrap: the same drawn family indices for every contrast.

    contrasts: name -> (A column, C column). Returns name -> array of resampled gains (percent).
    """
    fam = list(families(rows).values())
    m = len(fam)
    if m < 2:
        return {"available": False, "reason": "fewer than two independent families", "m": m}
    sums = {}
    for name, (a, c) in contrasts.items():
        sums[name] = (np.array([_sum(rs, a) for rs in fam], dtype=np.float64),
                      np.array([_sum(rs, c) for rs in fam], dtype=np.float64))
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = {name: np.empty(resamples) for name in contrasts}
    undefined = {name: 0 for name in contrasts}
    done = 0
    while done < resamples:
        k = min(chunk, resamples - done)
        idx = rng.integers(0, m, size=(k, m))
        for name, (fa, fc) in sums.items():
            sa = fa[idx].sum(axis=1)
            sc = fc[idx].sum(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                g = np.where(sa > 0, 100.0 * (sa - sc) / sa, np.nan)
            undefined[name] += int(np.isnan(g).sum())
            draws[name][done:done + k] = g
        done += k
    return {"available": True, "m": m, "draws": draws, "undefined": undefined}


def intervals(draws: np.ndarray, level: float, k: int) -> dict:
    alpha = 1.0 - level
    finite = draws[np.isfinite(draws)]
    if finite.size == 0:
        return {"available": False}
    lo, hi = np.quantile(finite, [alpha / 2, 1 - alpha / 2], method="linear")
    blo, bhi = np.quantile(finite, [alpha / (2 * k), 1 - alpha / (2 * k)], method="linear")
    return {"available": True, "marginal": [float(lo), float(hi)], "marginal_probs": [alpha / 2, 1 - alpha / 2],
            "bonferroni": [float(blo), float(bhi)], "bonferroni_probs": [alpha / (2 * k), 1 - alpha / (2 * k)]}


def cstar_selection(pilot_rows, candidates=("D", "P"), tie="P") -> dict:
    tot = {p: _sum(pilot_rows, f"C_{p}") for p in candidates}
    a, b = candidates
    if tot[a] < tot[b]:
        sel = a
    elif tot[b] < tot[a]:
        sel = b
    else:
        sel = tie
    return {"selected": sel, "totals": tot, "rule": f"smaller pilot aggregate of {a}/{b}; ties -> {tie}"}


def pilot_targets(rows) -> dict:
    sb, sc = _sum(rows, "B"), _sum(rows, "C_G")
    fo = family_outcomes(rows, "B", "C_G")
    return {
        "gain_vs_brotli_percent": gain(rows, "B", "C_G"),
        "size_target_met": 100 * (sb - sc) >= sb,
        "family_wins": fo["wins"], "m": fo["m"],
        "breadth_target_met": 3 * fo["wins"] >= 2 * fo["m"],
    }


def claim_criteria(rows, ints: dict, cstar: str, coverage_exact: bool) -> dict:
    remaining = "P" if cstar == "D" else "D"
    sb, sc = _sum(rows, "B"), _sum(rows, "C_G")
    fo = family_outcomes(rows, "B", "C_G")
    lows = {k: (v.get("bonferroni") or [None])[0] for k, v in ints.items()}
    g_vs_i = gain(rows, "C_I", "C_G")
    crit = {
        "exact_paired_coverage": coverage_exact,
        "adjusted_lower_endpoints_positive": all(v is not None and v > 0 for v in lows.values()) and len(lows) == 3,
        "G_total_below_remaining_control": sc < _sum(rows, f"C_{remaining}"),
        "raw_brotli_gain_at_least_1_percent": 100 * (sb - sc) >= sb,
        "strict_family_wins_two_thirds": 3 * fo["wins"] >= 2 * fo["m"],
        "family_wins": fo["wins"], "m": fo["m"], "ceil_2m_over_3": math.ceil(2 * fo["m"] / 3),
        "G_vs_I_positive": g_vs_i is not None and g_vs_i > 0,
        "remaining_control": remaining, "adjusted_lower_endpoints": lows,
    }
    crit["broad_success_claim"] = all(crit[k] for k in ("exact_paired_coverage", "adjusted_lower_endpoints_positive",
                                                        "G_total_below_remaining_control", "raw_brotli_gain_at_least_1_percent",
                                                        "strict_family_wins_two_thirds", "G_vs_I_positive"))
    lb = lows.get("G_vs_brotli11")
    crit["lower_bound_exceeds_1_percent"] = lb is not None and lb > 1.0
    return crit

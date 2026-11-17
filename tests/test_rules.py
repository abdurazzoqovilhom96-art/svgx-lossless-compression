"""Spelling rules, descriptors, arithmetic-coder golden streams and the reduced probability fixture."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("X,K,expected", [
    (10, 0, [b"10", b"10.0", b"10.00", b"10.000", b"10.0000", b"10", b"10", b"10.00"]),
    (0, 3, [b"0", b"0.0", b"0.00", b"0.000", b"0.0000", b"0", b"0", b"0.00"]),
    (-5, 1, [None, b"-0.5", b"-0.50", b"-0.500", b"-0.5000", b"-0.5", b"-.5", b"-.50"]),
    (12345, 3, [None, None, None, b"12.345", b"12.3450", b"12.345", b"12.345", None]),
    (5, 1, [None, b"0.5", b"0.50", b"0.500", b"0.5000", b"0.5", b".5", b".50"]),
])
def test_rule_outputs(ref, X, K, expected):
    assert ref.rule_outputs(X, K) == expected


@pytest.mark.parametrize("text,K", [(b".5", 1), (b"0.50", 2), (b"+5E-01", 1), (b"5.", 0), (b"-0", 0), (b"1e-005", 5),
                                    (b"00.5", 1), (b"-.75", 2), (b"7E+0", 3), (b"-0.000", 3)])
def test_descriptor_roundtrip(ref, text, K):
    m, neg, k, e = ref.lexeme_value(text)
    X = (-1 if neg else 1) * m * 10 ** (e - k + K)
    sign = 1 if text[:1] == b"-" else 2 if text[:1] == b"+" else 0
    body = text.lstrip(b"+-")
    mant = body.split(b"e")[0].split(b"E")[0]
    exp = body[len(mant):]
    d = ref.Desc(sign, len(mant.replace(b".", b"")), k, b"." in mant, exp)
    assert d.render(X, K) == text


def test_descriptor_compatibility(ref):
    d = ref.Desc(0, 1, 1, True, b"")       # ".5" style
    assert d.render(-5, 1) is None          # sign incompatible
    assert d.render(5, 2) is None           # 0.05 does not fit 1 digit
    assert ref.Desc(1, 1, 0, False, b"").render(0, 0) == b"-0"


def test_reduced_fixture_probabilities():
    """Rules fixed-one-place, shortest-L, fixed-two-places and escape with weight one at v = 1/2."""
    outs = [b"0.5", b"0.5", b"0.50"]
    w = [1, 1, 1]

    def prob(profile, y):
        if profile == "I":
            syms = list(zip(outs, w))
            idx = min(i for i, o in enumerate(outs) if o == y)
            return syms[idx][1], sum(w) + 1
        groups = {}
        for o, x in zip(outs, w):
            groups.setdefault(o, []).append(x)
        agg = max if profile == "U" else sum
        return agg(groups[y]), sum(agg(v) for v in groups.values()) + 1

    assert prob("I", b"0.5") == (1, 4)
    assert prob("U", b"0.5") == (1, 3)
    assert prob("G", b"0.5") == (2, 4)
    assert prob("U", b"0.50") == (1, 3)
    assert prob("G", b"0.50") == (1, 4)


def test_arith_golden_streams(ref):
    """Hand-derived WNC streams (FORMAT.md §10)."""
    d = ref.ArithDecoder(bytes([0b0100_0000]), 2)       # no symbols
    d.done()
    d = ref.ArithDecoder(bytes([0b0010_0000]), 3)       # symbol 0 of [1, 1]
    assert d.symbol([1, 1]) == 0
    d.done()
    d = ref.ArithDecoder(bytes([0b1010_0000]), 3)       # symbol 1 of [1, 1]
    assert d.symbol([1, 1]) == 1
    d.done()
    d = ref.ArithDecoder(bytes([0b0010_0000]), 4)       # non-canonical bit count
    d.symbol([1, 1])
    with pytest.raises(ref.FormatError):
        d.done()


def test_rounding_half_even(ref):
    assert [ref.rnd(n, 2) for n in (-5, -3, -1, 1, 3, 5)] == [-2, -2, 0, 0, 2, 2]
    assert ref.rnd(7, 3) == 2 and ref.rnd(-7, 3) == -2 and ref.rnd(8, 3) == 3


def test_affine_prediction_and_singular(ref):
    T = ((2, 0), (0, 2))
    Q = ((1, 0), (0, 1))
    assert ref.affine_predict(T, Q, (3, -4)) == (6, -8)
    with pytest.raises(ref.Unavailable):
        ref.affine_predict(T, ((1, 1), (2, 2)), (1, 1))
    with pytest.raises(ref.Unavailable):
        ref.best_triple([(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)])
    assert ref.affine_predict(((1, 0), (0, 1)), ((2, 0), (0, 2)), (1, 3)) == (0, 2)  # 0.5 -> 0, 1.5 -> 2

"""REV1 B1: extraction of the structured-stream internals and the two non-codec ablation sections T and Z.

* `extract(stream)` decodes a structured SVGX stream with the UNCHANGED frozen reference decoder
  (reference/decode.py) and records, through wrappers around two of its module functions, the literal stream U,
  the schedule, the hole list (role, X, K) and the restored lexemes. The decoder's own checks (lengths, CRC-32)
  run unchanged; the wrappers only copy return values.
* T ("separation only"): the hole lexemes, joined by single spaces (lexemes never contain spaces), are stored as
  one extra Brotli stream. S_T = 60 + |literals| + |schedule| + |Brotli(holes_text)|.
* Z ("values as written, no prediction"): the grid values X of the 16 holes of each block are zig-zag mapped and
  coded with an order-p exponential-Golomb code, p in 0..15 chosen per block (4 bits), exactly like the codec's
  residual code but without any prediction and without a mode field.
  S_Z = 60 + |literals| + |schedule| + ceil(bits_Z/8) + |spelling_G| + |escapes_G|.
Both sections are encoded AND decoded here; callers must check `roundtrip_ok`.
"""
from __future__ import annotations

import importlib.util
import struct

from common import REF_DECODER

_REF = None


def ref():
    global _REF
    if _REF is None:
        spec = importlib.util.spec_from_file_location("svgx_reference_decode", REF_DECODER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _REF = mod
    return _REF


HEADER = struct.Struct("<BBBBQIIIIQIQIII")  # FORMAT.md §2: 60 bytes
assert HEADER.size == 60


def parse_header(stream: bytes) -> dict:
    keys = ("marker", "version", "profile", "flags", "source_length", "crc32", "literal_len", "schedule_len",
            "geometry_len", "geometry_bits", "spelling_len", "spelling_bits", "escape_len", "escape_count", "hole_count")
    h = dict(zip(keys, HEADER.unpack_from(stream, 0)))
    o = 60
    for name in ("literal", "schedule", "geometry", "spelling", "escape"):
        n = h[name + "_len"]
        h[name + "_bytes"] = stream[o:o + n]
        o += n
    assert o == len(stream), "section lengths do not reconcile"
    return h


def extract(stream: bytes) -> dict:
    """Decode a structured stream with the frozen reference decoder and capture its intermediate values."""
    mod = ref()
    calls, cap = [], {}
    orig_br, orig_sp = mod.brotli_strict, mod.decode_spelling

    def br(data, limit):
        out = orig_br(data, limit)
        calls.append(out)
        return out

    def sp(profile, holes, sec, nbits, escapes):
        lex = orig_sp(profile, holes, sec, nbits, escapes)
        cap["holes"] = list(holes)
        cap["lex"] = list(lex)
        return lex

    mod.brotli_strict, mod.decode_spelling = br, sp
    try:
        restored = mod.decode_structured(stream)
    finally:
        mod.brotli_strict, mod.decode_spelling = orig_br, orig_sp
    h = parse_header(stream)
    U, sched = calls[0], calls[1]
    positions = schedule_positions(sched, h["hole_count"])
    assert len(cap["lex"]) == h["hole_count"] == len(positions)
    return {"restored": restored, "header": h, "U": U, "schedule": sched, "positions": positions,
            "holes": cap["holes"], "lex": cap["lex"]}


def schedule_positions(sched: bytes, hole_count: int) -> list[int]:
    leb = ref().leb
    p = 0
    n_paths, p = leb(sched, p)
    for _ in range(n_paths):
        for _ in range(4):
            _, p = leb(sched, p)
    pos, acc = [], 0
    for _ in range(hole_count):
        g, p = leb(sched, p)
        acc += g
        pos.append(acc)
    assert p == len(sched)
    return pos


def interleave(U: bytes, positions: list[int], lex: list[bytes]) -> bytes:
    parts, last = [], 0
    for q, y in zip(positions, lex):
        parts.append(U[last:q])
        parts.append(y)
        last = q
    parts.append(U[last:])
    return b"".join(parts)


# ---------------------------------------------------------------- T: separation only
def t_holes_text(lex: list[bytes]) -> bytes:
    assert all(b" " not in y and len(y) > 0 for y in lex)
    return b" ".join(lex)


def t_decode(holes_text_compressed: bytes, U: bytes, positions: list[int], expect_holes: int) -> bytes:
    text = ref().brotli_strict(holes_text_compressed, 1 << 31)
    lex = text.split(b" ") if expect_holes else []
    assert len(lex) == expect_holes
    return interleave(U, positions, lex)


# ---------------------------------------------------------------- Z: values as written, exp-Golomb, no prediction
def zig(r: int) -> int:
    return 2 * r if r >= 0 else -2 * r - 1


def unzig(z: int) -> int:
    return z >> 1 if z % 2 == 0 else -((z + 1) >> 1)


def gamma_len(n: int) -> int:
    return 2 * (n.bit_length() - 1) + 1


class BitWriter:
    """MSB-first bit writer; zero padding to a whole byte (same convention as the codec's sections)."""

    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.nacc = 0
        self.nbits = 0

    def put(self, v: int, n: int):
        if n == 0:
            return
        assert 0 <= v < (1 << n)
        self.acc = (self.acc << n) | v
        self.nacc += n
        self.nbits += n
        while self.nacc >= 8:
            self.nacc -= 8
            self.out.append((self.acc >> self.nacc) & 0xFF)
        self.acc &= (1 << self.nacc) - 1

    def gamma(self, n: int):
        assert n >= 1
        k = n.bit_length() - 1
        self.put(0, k)
        self.put(n, k + 1)

    def to_bytes(self) -> bytes:
        out = bytes(self.out)
        if self.nacc:
            out += bytes([(self.acc << (8 - self.nacc)) & 0xFF])
        assert len(out) == (self.nbits + 7) // 8
        return out


class BitReader:
    def __init__(self, data: bytes, nbits: int):
        assert len(data) == (nbits + 7) // 8, "section length does not match its bit count"
        self.data = bytes(data)
        self.nbits, self.i = nbits, 0
        pad = len(data) * 8 - nbits
        if pad:  # padding bits must be zero
            assert data[-1] & ((1 << pad) - 1) == 0, "non-zero padding"

    def get(self, n: int) -> int:
        if n == 0:
            return 0
        assert self.i + n <= self.nbits, "read past end"
        b0, b1 = self.i >> 3, (self.i + n + 7) >> 3
        chunk = int.from_bytes(self.data[b0:b1], "big")
        v = (chunk >> (b1 * 8 - self.i - n)) & ((1 << n) - 1)
        self.i += n
        return v

    def bit(self) -> int:
        return self.get(1)

    def gamma(self) -> int:
        k = 0
        while self.bit() == 0:
            k += 1
        return (1 << k) | self.get(k)


def z_encode(values: list[int]) -> tuple[bytes, int]:
    """values: hole values X in hole order (16 per block). Returns (bytes, valid bits)."""
    assert len(values) % 16 == 0
    w = BitWriter()
    for b in range(0, len(values), 16):
        zs = [zig(x) for x in values[b:b + 16]]
        best = min(range(16), key=lambda p: (sum(gamma_len((z >> p) + 1) + p for z in zs), p))
        w.put(best, 4)
        for z in zs:
            w.gamma((z >> best) + 1)
            if best:
                w.put(z & ((1 << best) - 1), best)
    return w.to_bytes(), w.nbits


def tz_arms(forced_g: bytes, original: bytes, brotli_compress) -> dict:
    """Sizes and round trips of the T and Z sections for one file, from its forced G stream.

    `brotli_compress(bytes) -> bytes` must be the codec's own Brotli (quality 11, lgwin 22), i.e. `svgx raw`.
    """
    mod = ref()
    x = extract(forced_g)
    h = x["header"]
    assert h["profile"] == 5, "forced stream is not profile G"
    assert x["restored"] == original, "reference decoder did not restore the original"
    base = 60 + h["literal_len"] + h["schedule_len"]
    # ---- T
    text = t_holes_text(x["lex"])
    t_sec = brotli_compress(text)
    t_ok = t_decode(t_sec, x["U"], x["positions"], h["hole_count"]) == original
    # ---- Z
    values = [hv[1] for hv in x["holes"]]
    z_sec, z_bits = z_encode(values)
    dec_vals = z_decode(z_sec, z_bits, len(values))
    escapes = []
    if h["escape_count"]:
        escapes = mod.read_descriptors(mod.brotli_strict(h["escape_bytes"], 64 * (h["escape_count"] + 1)), h["escape_count"])
    holes_z = [(role, xv, k) for (role, _, k), xv in zip(x["holes"], dec_vals)]
    lex_z = mod.decode_spelling("G", holes_z, h["spelling_bytes"], h["spelling_bits"], escapes)
    z_ok = dec_vals == values and interleave(x["U"], x["positions"], lex_z) == original
    return {
        "hole_count": h["hole_count"], "literal_len": h["literal_len"], "schedule_len": h["schedule_len"],
        "geometry_len_G": h["geometry_len"], "geometry_bits_G": h["geometry_bits"],
        "spelling_len_G": h["spelling_len"], "escape_len_G": h["escape_len"],
        "holes_text_len": len(text), "T_section_len": len(t_sec), "S_T": base + len(t_sec), "T_roundtrip_ok": t_ok,
        "Z_section_len": len(z_sec), "Z_bits": z_bits,
        "S_Z": base + len(z_sec) + h["spelling_len"] + h["escape_len"], "Z_roundtrip_ok": z_ok,
    }


def z_decode(data: bytes, nbits: int, count: int) -> list[int]:
    r = BitReader(data, nbits)
    out = []
    for _ in range(count // 16):
        p = r.get(4)
        for _ in range(16):
            q = r.gamma() - 1
            low = r.get(p) if p else 0
            out.append(unzig((q << p) | low))
    assert r.i == nbits
    return out

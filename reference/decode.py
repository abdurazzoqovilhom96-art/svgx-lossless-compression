#!/usr/bin/env python3
"""Independent reference decoder for SVGX v1.

Implemented from the public specification docs/FORMAT.md only (it shares no code with the Rust
codec). Dependencies: the Python standard library and the `brotli` module for the standard Brotli
sections. Usage:  python reference/decode.py INPUT OUTPUT   (exit 0 ok, 2 usage, 3 I/O, 4 format)
"""
from __future__ import annotations

import struct
import sys
import zlib

import brotli

MAX_SOURCE = 1 << 30
BOUND = 1 << 126          # every bounded intermediate satisfies |x| < BOUND
COORD = 1 << 96           # absolute grid coordinates satisfy |x| < COORD
WINDOW = 4096
RESCALE = 16384
PROFILES = {1: "D", 2: "P", 3: "I", 4: "U", 5: "G"}
WSP = b" \t\n\r"


class FormatError(Exception):
    """The input is not a valid SVGX v1 / standard Brotli stream."""


class Unavailable(Exception):
    """A bounded computation exceeded the frozen bound."""


def need(cond: bool, msg: str) -> None:
    if not cond:
        raise FormatError(msg)


# ----------------------------------------------------------------------------- Brotli sections

def brotli_strict(data: bytes, limit: int) -> bytes:
    """Standard decode (large window disabled by default); the one-shot API rejects corrupt,
    truncated and trailing input (verified by tests/test_format.py)."""
    need(len(data) > 0, "empty Brotli stream")
    try:
        out = brotli.decompress(data)
    except brotli.error as exc:
        raise FormatError(f"invalid Brotli stream (corrupt, truncated or trailing bytes): {exc}") from None
    need(len(out) <= limit, "Brotli output exceeds limit")
    return out


# ----------------------------------------------------------------------------- integers / bits

def leb(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    start = pos
    while True:
        need(pos < len(data), "LEB128 truncated")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            need(not (byte == 0 and pos - start > 1), "LEB128 not canonical")
            need(value < (1 << 64), "LEB128 overflow")
            return value, pos
        shift += 7
        need(shift <= 63, "LEB128 too long")


class Bits:
    """MSB-first reader; `strict` forbids reading past the valid bit count."""

    def __init__(self, data: bytes, nbits: int, strict: bool):
        self.data = data
        self.nbits = nbits
        self.strict = strict
        self.i = 0

    def bit(self) -> int:
        if self.i >= self.nbits:
            if self.strict:
                raise FormatError("read past valid bits")
            self.i += 1
            return 0
        b = (self.data[self.i >> 3] >> (7 - (self.i & 7))) & 1
        self.i += 1
        return b

    def read(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def gamma(self) -> int:
        zeros = 0
        while self.bit() == 0:
            zeros += 1
            need(zeros <= 127, "gamma code too long")
        return (1 << zeros) | self.read(zeros)

    def leb(self) -> int:
        octets = []
        while True:
            o = self.read(8)
            octets.append(o)
            if not o & 0x80:
                break
            need(len(octets) <= 10, "LEB128 too long")
        v, end = leb(bytes(octets), 0)
        need(end == len(octets), "LEB128 framing")
        return v


def check_section_bits(sec: bytes, nbits: int, what: str) -> None:
    need(len(sec) == (nbits + 7) // 8, f"{what}: length/bit-count mismatch")
    if nbits % 8:
        need(sec[-1] & (0xFF >> (nbits % 8)) == 0, f"{what}: non-zero padding")


# ----------------------------------------------------------------------------- numbers

def scan_number(b: bytes, i: int, lim: int, signed: bool):
    """Greedy SVG number scan; returns end index or None."""
    j = i
    if signed and j < lim and b[j] in b"+-":
        j += 1
    d0 = j
    while j < lim and 48 <= b[j] <= 57:
        j += 1
    n_int = j - d0
    n_frac = 0
    if j < lim and b[j] == 46:  # '.'
        f0 = j + 1
        f = f0
        while f < lim and 48 <= b[f] <= 57:
            f += 1
        n_frac = f - f0
        if n_int or n_frac:
            j = f
    if n_int + n_frac == 0:
        return None
    if j < lim and b[j] in b"eE":
        e = j + 1
        if e < lim and b[e] in b"+-":
            e += 1
        if e < lim and 48 <= b[e] <= 57:
            while e < lim and 48 <= b[e] <= 57:
                e += 1
            j = e
    return j


def lexeme_value(tok: bytes):
    """Return (mantissa M, signed?, k, e) of an exact lexeme with frozen bounds, else raise."""
    n = len(tok)
    need(0 < n <= 64, "lexeme length")
    digit = lambda c: 48 <= c <= 57  # noqa: E731
    i = 0
    neg = False
    if tok[0] in b"+-":
        neg = tok[0] == 0x2D
        i = 1
    s0 = i
    while i < n and digit(tok[i]):
        i += 1
    ip = tok[s0:i]
    fp = b""
    if i < n and tok[i] == 0x2E:
        i += 1
        f0 = i
        while i < n and digit(tok[i]):
            i += 1
        fp = tok[f0:i]
    need(len(ip) + len(fp) >= 1, "mantissa")
    e = 0
    if i < n:
        need(tok[i] in b"eE", "lexeme syntax")
        i += 1
        e0 = i
        if i < n and tok[i] in b"+-":
            i += 1
        d0 = i
        while i < n and digit(tok[i]):
            i += 1
        need(i == n and d0 < i <= d0 + 6, "exponent")
        e = int(tok[e0:n])
    w = len(ip) + len(fp)
    need(w <= 38 and abs(e) <= 18, "lexeme bounds")
    return int(ip + fp), neg, len(fp), e


def grid(tok: bytes, K: int) -> int:
    m, neg, k, e = lexeme_value(tok)
    s = e - k + K
    need(s >= 0, "literal coordinate off-grid")
    x = m * 10 ** s
    need(x < COORD, "coordinate out of bounds")
    return -x if neg else x


class Desc:
    __slots__ = ("sign", "w", "k", "dot", "exp")

    def __init__(self, sign, w, k, dot, exp):
        self.sign, self.w, self.k, self.dot, self.exp = sign, w, k, dot, exp

    def render(self, X: int, K: int):
        e = int(self.exp[1:]) if self.exp else 0
        t = self.k - e - K
        ax = abs(X)
        if t >= 0:
            M = ax * 10 ** t
        else:
            q, r = divmod(ax, 10 ** (-t))
            if r:
                return None
            M = q
        if M >= 10 ** self.w:
            return None
        if (X < 0 and self.sign != 1) or (X > 0 and self.sign == 1):
            return None
        digits = str(M).rjust(self.w, "0")
        body = digits[: self.w - self.k] + "." + digits[self.w - self.k:] if self.dot else digits
        return ({1: "-", 2: "+"}.get(self.sign, "") + body).encode("ascii") + self.exp


def read_descriptors(raw: bytes, count: int) -> list:
    out = []
    p = 0
    for _ in range(count):
        need(p + 3 <= len(raw), "descriptor truncated")
        flags, w, k = raw[p], raw[p + 1], raw[p + 2]
        p += 3
        need(flags & 0xF0 == 0 and flags & 3 != 3, "descriptor flags")
        dot = bool(flags & 4)
        need(1 <= w <= 38 and k <= w and (dot or k == 0), "descriptor w/k")
        exp = b""
        if flags & 8:
            need(p < len(raw), "descriptor exponent truncated")
            n = raw[p]
            p += 1
            need(2 <= n <= 8 and p + n <= len(raw), "descriptor exponent length")
            exp = raw[p:p + n]
            p += n
            body = exp[1:]
            if body[:1] in (b"+", b"-"):
                body = body[1:]
            need(exp[:1] in (b"e", b"E") and body.isdigit() and 1 <= len(body) <= 6, "descriptor exponent")
            need(abs(int(exp[1:])) <= 18, "descriptor exponent bound")
        out.append(Desc(flags & 3, w, k, dot, exp))
    need(p == len(raw), "escape stream has trailing bytes")
    return out


# ----------------------------------------------------------------------------- rules (FORMAT §8)

def fixed_point(X: int, K: int, d: int, short: bool):
    if d >= K:
        N = abs(X) * 10 ** (d - K)
    else:
        N, r = divmod(abs(X), 10 ** (K - d))
        if r:
            return None
    s = str(N).rjust(d + 1, "0")
    ip, fp = s[: len(s) - d], s[len(s) - d:]
    if short and ip == "0" and N:
        ip = ""
    text = ("-" if X < 0 else "") + ip + ("." + fp if d else "")
    return text.encode("ascii")


def min_places(X: int, K: int) -> int:
    if X == 0:
        return 0
    d, a = K, abs(X)
    while d and a % 10 == 0:
        a //= 10
        d -= 1
    return d


def rule_outputs(X: int, K: int) -> list:
    sp = min_places(X, K)
    return [fixed_point(X, K, 0, False), fixed_point(X, K, 1, False), fixed_point(X, K, 2, False),
            fixed_point(X, K, 3, False), fixed_point(X, K, 4, False), fixed_point(X, K, sp, False),
            fixed_point(X, K, sp, True), fixed_point(X, K, 2, True)]


# ----------------------------------------------------------------------------- arithmetic decoder

class ArithDecoder:
    HALF, Q1, Q3, TOP = 1 << 31, 1 << 30, 3 << 30, (1 << 32) - 1

    def __init__(self, data: bytes, nbits: int):
        self.bits = Bits(data, nbits, strict=False)
        self.nbits = nbits
        self.lo, self.hi, self.shifts = 0, self.TOP, 0
        self.val = self.bits.read(32)

    def symbol(self, freqs: list) -> int:
        total = sum(freqs)
        span = self.hi - self.lo + 1
        target = ((self.val - self.lo + 1) * total - 1) // span
        acc = 0
        for s, f in enumerate(freqs):
            if target < acc + f:
                break
            acc += f
        else:
            raise FormatError("arithmetic target outside alphabet")
        self.hi = self.lo + span * (acc + f) // total - 1
        self.lo = self.lo + span * acc // total
        while True:
            if self.hi < self.HALF:
                pass
            elif self.lo >= self.HALF:
                self.lo -= self.HALF
                self.hi -= self.HALF
                self.val -= self.HALF
            elif self.lo >= self.Q1 and self.hi < self.Q3:
                self.lo -= self.Q1
                self.hi -= self.Q1
                self.val -= self.Q1
            else:
                break
            self.lo = 2 * self.lo
            self.hi = 2 * self.hi + 1
            self.val = 2 * self.val + self.bits.bit()
            self.shifts += 1
        return s

    def done(self) -> None:
        need(self.nbits == self.shifts + 2, "arithmetic code: non-canonical bit count")
        need(self.val == (self.Q1 if self.lo < self.Q1 else self.HALF), "arithmetic code: non-canonical tail")


# ----------------------------------------------------------------------------- masked path grammar

class Cursor:
    def __init__(self, b: bytes, holes: list):
        self.b, self.holes, self.i, self.h = b, holes, 0, 0

    def hole_here(self) -> bool:
        return self.h < len(self.holes) and self.holes[self.h] == self.i

    def ch(self):
        if self.hole_here() or self.i >= len(self.b):
            return None
        return self.b[self.i]

    def wsp(self) -> None:
        while self.ch() is not None and self.ch() in WSP:
            self.i += 1

    def sep(self) -> str:
        c = self.ch()
        if c is None:
            return ""
        if c in WSP:
            self.wsp()
            if self.ch() == 0x2C:
                self.i += 1
                self.wsp()
                return ","
            return " "
        if c == 0x2C:
            self.i += 1
            self.wsp()
            return ","
        return ""

    def num(self, signed=True):
        if self.hole_here():
            self.h += 1
            return ("H", self.h - 1)
        lim = self.holes[self.h] if self.h < len(self.holes) else len(self.b)
        end = scan_number(self.b, self.i, lim, signed)
        need(end is not None, "path grammar: number expected")
        tok = ("N", self.b[self.i:end])
        self.i = end
        return tok

    def flag(self):
        c = self.ch()
        need(c in (0x30, 0x31), "path grammar: flag expected")
        self.i += 1
        return ("N", bytes([c]))

    def starts_number(self) -> bool:
        if self.hole_here():
            return True
        c = self.ch()
        return c is not None and (48 <= c <= 57 or c in b".+-")


ARITY = {"M": "pp", "L": "pp", "T": "pp", "H": "n", "V": "n", "C": "pppppp", "S": "pppp", "Q": "pppp",
         "A": "a"}


def parse_masked(b: bytes, holes: list) -> list:
    """Return groups [cmd(upper), rel, [tokens]]; implicit lineto after moveto reported as L."""
    cur = Cursor(b, holes)
    groups = []
    cur.wsp()
    first = True
    while True:
        cur.wsp()
        if cur.hole_here():
            raise FormatError("path grammar: hole where a command is expected")
        c = cur.ch()
        if c is None:
            break
        letter = chr(c)
        up = letter.upper()
        need(up in "MZLHVCSQTA", "path grammar: unknown command")
        need(not first or up == "M", "path grammar: must start with moveto")
        first = False
        cur.i += 1
        rel = letter.islower()
        if up == "Z":
            groups.append(["Z", rel, []])
            continue
        cur.wsp()
        k = 0
        while True:
            args = []
            if up == "A":
                args.append(cur.num(False)); cur.sep()
                args.append(cur.num(False)); cur.sep()
                args.append(cur.num(True))
                need(cur.sep() != "", "path grammar: separator before arc flag")
                args.append(cur.flag()); cur.sep()
                args.append(cur.flag()); cur.sep()
                args.append(cur.num(True)); cur.sep()
                args.append(cur.num(True))
            else:
                n = {"pp": 2, "n": 1, "pppp": 4, "pppppp": 6}[ARITY[up]]
                for idx in range(n):
                    if idx:
                        cur.sep()
                    args.append(cur.num(True))
            groups.append(["L" if (up == "M" and k) else up, rel, args])
            k += 1
            save = (cur.i, cur.h)
            s = cur.sep()
            if cur.starts_number():
                continue
            need(s != ",", "path grammar: dangling comma")
            cur.i, cur.h = save
            break
    need(cur.h == len(holes), "path grammar: unconsumed holes")
    return groups


def cubic_blocks(groups: list) -> list:
    out, i = [], 0
    while i < len(groups):
        if groups[i][0] != "C":
            i += 1
            continue
        j = i
        while j < len(groups) and groups[j][0] == "C":
            j += 1
        for q in range((j - i) // 4):
            out.append(list(range(i + 4 * q, i + 4 * q + 4)))
        i = j
    return out


ENDPOINT = {"M": (0, 1), "L": (0, 1), "T": (0, 1), "C": (4, 5), "S": (2, 3), "Q": (2, 3), "A": (5, 6)}


def walk_points(groups: list, K: int) -> list:
    """(start, end) current points per group from literal endpoint tokens."""
    def val(tok):
        need(tok[0] == "N", "hole at an endpoint")
        return grid(tok[1], K)

    x = y = 0
    sx = sy = 0
    res = []
    for cmd, rel, args in groups:
        start = (x, y)
        if cmd == "Z":
            x, y = sx, sy
        elif cmd == "H":
            v = val(args[0])
            x = x + v if rel else v
        elif cmd == "V":
            v = val(args[0])
            y = y + v if rel else v
        else:
            a, b2 = ENDPOINT[cmd]
            vx, vy = val(args[a]), val(args[b2])
            x, y = (x + vx, y + vy) if rel else (vx, vy)
        need(abs(x) < COORD and abs(y) < COORD, "current point out of bounds")
        if cmd == "M":
            sx, sy = x, y
        res.append((start, (x, y)))
    return res


# ----------------------------------------------------------------------------- geometry (FORMAT §7)

def b(v: int) -> int:
    if abs(v) >= BOUND:
        raise Unavailable
    return v


def rnd(n: int, d: int) -> int:
    q, r = divmod(n, d)
    if 2 * r > d or (2 * r == d and q % 2):
        q += 1
    return q


def tdet(u, v) -> int:
    return b(b(u[0] * v[1]) - b(v[0] * u[1]))


def best_triple(J):
    best, bestv = None, -1
    for a in range(5):
        for bb in range(a + 1, 5):
            for c in range(bb + 1, 5):
                u = (b(J[bb][0] - J[a][0]), b(J[bb][1] - J[a][1]))
                v = (b(J[c][0] - J[a][0]), b(J[c][1] - J[a][1]))
                d = abs(tdet(u, v))
                if d > bestv:
                    best, bestv = (a, bb, c), d
    if bestv == 0:
        raise Unavailable
    return best


def columns(J, t):
    a, bb, c = t
    return ((b(J[bb][0] - J[a][0]), b(J[bb][1] - J[a][1])), (b(J[c][0] - J[a][0]), b(J[c][1] - J[a][1])))


def affine_predict(T, Q, h):
    (q00, q10), (q01, q11) = Q
    det = b(b(q00 * q11) - b(q01 * q10))
    if det == 0:
        raise Unavailable
    ux = b(b(q11 * h[0]) - b(q01 * h[1]))
    uy = b(b(q00 * h[1]) - b(q10 * h[0]))
    (t00, t10), (t01, t11) = T
    nx = b(b(t00 * ux) + b(t01 * uy))
    ny = b(b(t10 * ux) + b(t11 * uy))
    if det < 0:
        nx, ny, det = -nx, -ny, -det
    return (rnd(nx, det), rnd(ny, det))


def reflect_h1(c, h0):
    D = b(b(c[0] * c[0]) + b(c[1] * c[1]))
    if D == 0:
        return (0, 0)
    dot = b(b(c[0] * h0[0]) + b(c[1] * h0[1]))
    out = []
    for i in range(2):
        n = b(b(2 * b(c[i] * dot)) - b(h0[i] * D))
        out.append(rnd(n, D))
    return tuple(out)


def read_scalar(bits: Bits, p: int) -> int:
    n = bits.gamma()
    z = ((n - 1) << p) | bits.read(p)
    need(z < (1 << 127), "residual too large")
    r = z >> 1 if z % 2 == 0 else -(z >> 1) - 1
    need(abs(r) < BOUND, "residual out of bounds")
    return r


def decode_geometry(sec: bytes, nbits: int, junctions: list) -> list:
    bits = Bits(sec, nbits, strict=True)
    done = []  # per block: (J, h0 list, h1 list)
    for idx, J in enumerate(junctions):
        mode = bits.read(2)
        ref = T = Q = None
        if mode == 3:
            dist = bits.leb() + 1
            need(dist <= min(WINDOW, idx), "reference distance outside window")
            ref = done[idx - dist]
            try:
                tri = best_triple(J)
                T, Q = columns(J, tri), columns(ref[0], tri)
            except Unavailable:
                raise FormatError("mode 11 unavailable") from None
        p = bits.read(4)
        h0s, h1s = [], []
        for s in range(4):
            c = (J[s + 1][0] - J[s][0], J[s + 1][1] - J[s][1])
            try:
                if mode == 0:
                    ph0 = (0, 0)
                elif mode == 1 or (mode == 2 and s == 0):
                    ph0 = (rnd(c[0], 3), rnd(c[1], 3))
                elif mode == 2:
                    ph0 = h1s[s - 1]
                else:
                    ph0 = affine_predict(T, Q, ref[1][s])
            except Unavailable:
                raise FormatError("predictor unavailable") from None
            h0 = (ph0[0] + read_scalar(bits, p), ph0[1] + read_scalar(bits, p))
            try:
                if mode == 0:
                    ph1 = (0, 0)
                elif mode == 1:
                    ph1 = (rnd(c[0], 3), rnd(c[1], 3))
                elif mode == 2:
                    ph1 = reflect_h1(c, h0)
                else:
                    ph1 = affine_predict(T, Q, ref[2][s])
            except Unavailable:
                raise FormatError("predictor unavailable") from None
            h1 = (ph1[0] + read_scalar(bits, p), ph1[1] + read_scalar(bits, p))
            p1 = (J[s][0] + h0[0], J[s][1] + h0[1])
            p2 = (J[s + 1][0] - h1[0], J[s + 1][1] - h1[1])
            need(all(abs(v) < COORD for v in p1 + p2), "control point out of bounds")
            h0s.append(h0)
            h1s.append(h1)
        done.append((J, h0s, h1s))
    need(bits.i == nbits, "geometry: leftover bits")
    return done


# ----------------------------------------------------------------------------- spelling (FORMAT §9)

def decode_spelling(profile: str, holes: list, sec: bytes, nbits: int, escapes: list) -> list:
    """holes: list of (role, X, K). Returns lexeme bytes per hole."""
    esc_iter = iter(escapes)
    used = 0

    def take_escape():
        nonlocal used
        try:
            d = next(esc_iter)
        except StopIteration:
            raise FormatError("escape stream exhausted") from None
        used += 1
        return d

    if profile == "D":
        need(len(escapes) == len(holes), "D: escape count")
        out = []
        for (role, X, K), d in zip(holes, escapes):
            y = d.render(X, K)
            need(y is not None, "D: inapplicable descriptor")
            out.append(y)
        return out
    if not holes:
        need(nbits == 0 and not escapes, "spelling data without holes")
        return []
    ac = ArithDecoder(sec, nbits)
    weights = [[1] * 9 for _ in range(8)]
    flags = [[1, 1] for _ in range(8)]
    prev = [None] * 8
    out = []
    for role, X, K in holes:
        outs = rule_outputs(X, K)
        W = weights[role]
        if profile == "P":
            d0 = prev[role]
            cand = d0.render(X, K) if d0 is not None else None
            if cand is None:
                d = take_escape()
                y = d.render(X, K)
                need(y is not None, "P: inapplicable escape")
            else:
                f = flags[role]
                s = ac.symbol([f[0], f[1]])
                f[s] += 1
                if f[0] + f[1] >= RESCALE:
                    f[0], f[1] = (f[0] + 1) // 2, (f[1] + 1) // 2
                if s == 0:
                    y, d = cand, d0
                else:
                    d = take_escape()
                    y = d.render(X, K)
                    need(y is not None and y != cand, "P: invalid escape")
            prev[role] = d
        else:
            app = [i for i in range(8) if outs[i] is not None]
            if profile == "I":
                syms = [(outs[i], W[i]) for i in app]
            else:
                order, grp = [], {}
                for i in app:
                    if outs[i] not in grp:
                        grp[outs[i]] = []
                        order.append(outs[i])
                    grp[outs[i]].append(W[i])
                agg = max if profile == "U" else sum
                syms = [(o, agg(grp[o])) for o in order]
            s = ac.symbol([w for _, w in syms] + [W[8]])
            if s == len(syms):
                d = take_escape()
                y = d.render(X, K)
                need(y is not None, "inapplicable escape")
                need(y not in outs, "non-canonical escape")
            else:
                y = syms[s][0]
                if profile == "I":
                    top = max(W[i] for i in app if outs[i] == y)
                    first = min(i for i in app if outs[i] == y and W[i] == top)
                    need(app.index(first) == s, "non-canonical rule index")
        hits = [i for i in range(8) if outs[i] is not None and outs[i] == y]
        if hits:
            for i in hits:
                W[i] += 1
        else:
            W[8] += 1
        if sum(W) >= RESCALE:
            weights[role] = W = [(v + 1) // 2 for v in W]
        out.append(y)
    ac.done()
    need(used == len(escapes), "unused escape descriptors")
    return out


# ----------------------------------------------------------------------------- container

HEADER = struct.Struct("<4BQIIIIQIQIII")


def decode_structured(f: bytes) -> bytes:
    need(len(f) >= 60, "header truncated")
    (marker, version, prof, flags, src_len, crc, lit_len, sch_len, geo_len, geo_bits, sp_len, sp_bits,
     esc_len, esc_count, hole_count) = HEADER.unpack_from(f, 0)
    need(marker == 0x11 and version == 1, "marker/version")
    need(prof in PROFILES and flags == 0, "profile/flags")
    need(src_len <= MAX_SOURCE, "source length")
    need(60 + lit_len + sch_len + geo_len + sp_len + esc_len == len(f), "section lengths")
    need(hole_count % 16 == 0, "hole count")
    profile = PROFILES[prof]
    o = 60
    sec = []
    for n in (lit_len, sch_len, geo_len, sp_len, esc_len):
        sec.append(f[o:o + n])
        o += n
    lit, sch, geo, spl, esc = sec
    check_section_bits(geo, geo_bits, "geometry")
    if profile == "D" or hole_count == 0:
        need(sp_len == 0 and sp_bits == 0, "spelling must be empty")
    else:
        need(sp_bits > 0, "spelling missing")
        check_section_bits(spl, sp_bits, "spelling")
    U = brotli_strict(lit, src_len)
    S = brotli_strict(sch, 1 << 31)
    # schedule
    p = 0
    n_paths, p = leb(S, p)
    need(n_paths < 1 << 32, "path count")
    paths = []
    for _ in range(n_paths):
        sd, p = leb(S, p)
        ul, p = leb(S, p)
        K, p = leb(S, p)
        nb, p = leb(S, p)
        need(sd < 1 << 32 and ul < 1 << 32 and nb < 1 << 32 and K <= 18 and nb >= 1, "schedule fields")
        paths.append((sd, ul, K, nb))
    need(16 * sum(x[3] for x in paths) == hole_count, "schedule hole count")
    positions = []
    acc = 0
    for _ in range(hole_count):
        g, p = leb(S, p)
        need(g < 1 << 32, "gap bound")
        acc += g
        need(acc <= len(U), "hole beyond U")
        positions.append(acc)
    need(p == len(S), "schedule trailing bytes")
    # escapes
    if esc_count == 0:
        need(esc_len == 0, "escape section must be empty")
        escapes = []
    else:
        need(esc_len > 0, "escape section missing")
        escapes = read_descriptors(brotli_strict(esc, 64 * (esc_count + 1)), esc_count)
    if profile == "D":
        need(esc_count == hole_count, "D: escape count")
    # masked paths
    junctions, slots = [], []
    end = 0
    h = 0
    for sd, ul, K, nb in paths:
        start = end + sd
        end = start + ul
        need(end <= len(U), "path beyond U")
        mine = positions[h:h + 16 * nb]
        need(all(start <= q <= end for q in mine), "hole outside path span")
        groups = parse_masked(U[start:end], [q - start for q in mine])
        blocks = cubic_blocks(groups)
        need(len(blocks) == nb, "block count mismatch")
        member = {g: bi for bi, blk in enumerate(blocks) for g in blk}
        expect = 0
        for gi, (cmd, rel, args) in enumerate(groups):
            for a, tok in enumerate(args):
                slot = gi in member and a < 4
                if tok[0] == "H":
                    need(slot and tok[1] == expect, "hole placement")
                    expect += 1
                else:
                    need(not slot, "missing hole")
        pts = walk_points(groups, K)
        for blk in blocks:
            J = [pts[g][0] for g in blk] + [pts[blk[3]][1]]
            for s, g in enumerate(blk):
                for a in range(4):
                    slots.append((len(junctions), s, a, groups[g][1], K))
            junctions.append(J)
        h += 16 * nb
    need(h == hole_count, "unassigned holes")
    geom = decode_geometry(geo, geo_bits, junctions)
    holes = []
    for bi, s, a, rel, K in slots:
        J, h0s, h1s = geom[bi]
        comp = a % 2
        if a < 2:
            P = (J[s][0] + h0s[s][0], J[s][1] + h0s[s][1])
        else:
            P = (J[s + 1][0] - h1s[s][0], J[s + 1][1] - h1s[s][1])
        X = P[comp] - J[s][comp] if rel else P[comp]
        role = 4 * int(rel) + 2 * int(a >= 2) + comp
        holes.append((role, X, K))
    lex = decode_spelling(profile, holes, spl, sp_bits, escapes)
    need(len(U) + sum(len(x) for x in lex) == src_len, "reconstruction length")
    parts, last = [], 0
    for q, y in zip(positions, lex):
        parts.append(U[last:q])
        parts.append(y)
        last = q
    parts.append(U[last:])
    out = b"".join(parts)
    need(zlib.crc32(out) & 0xFFFFFFFF == crc, "CRC-32 mismatch")
    return out


def decode_bytes(f: bytes) -> bytes:
    need(len(f) > 0, "empty compressed stream")
    if f[0] == 0x11:
        return decode_structured(f)
    need(f[0] != 0x91, "0x91 (large-window Brotli) rejected")
    return brotli_strict(f, MAX_SOURCE)


def main(argv: list) -> int:
    if len(argv) != 3:
        sys.stderr.write("foydalanish: python reference/decode.py KIRISH CHIQISH\n")
        return 2
    try:
        with open(argv[1], "rb") as fh:
            data = fh.read()
    except OSError as exc:
        sys.stderr.write(f"xato: {exc}\n")
        return 3
    try:
        out = decode_bytes(data)
    except FormatError as exc:
        sys.stderr.write(f"xato: {exc}\n")
        return 4
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        sys.stderr.write(f"xato: format: {exc}\n")
        return 4
    try:
        with open(argv[2], "wb") as fh:
            fh.write(out)
    except OSError as exc:
        sys.stderr.write(f"xato: {exc}\n")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

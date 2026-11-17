# SVGX v1 — byte-exact SVG container format

Status: frozen for design `SVGX-2026-11-A` (see `config/study.toml`). This document is the public
specification from which both decoders (`codec/` in Rust and `reference/decode.py` in Python) are
implemented. Sections marked *normative* bind every decoder; sections marked *encoder* describe
the frozen encoder behaviour that the study measures.

Conventions: header integers are little-endian. Bit-packed sections are MSB-first: the first bit of
a section is bit 7 of its first byte. "LEB128" means canonical unsigned LEB128 (7-bit groups,
least significant group first, continuation flag 0x80; the final byte is non-zero unless the value is
0, which is the single byte 0x00). Brotli always means a standard RFC 7932 stream produced by the
pinned encoder (Google Brotli 1.2.1, quality 11, lgwin 22, mode generic) and decoded by a standard
decoder with large-window extensions disabled; the decoder must finish successfully and consume the
section exactly (no trailing bytes, no truncation).

## 1. Outer union (normative)

A compressed file `F` is decoded by its first octet:

| `F[0]` | Meaning |
|---|---|
| `F` empty | error (every source, including the empty source, has a non-empty stream) |
| `0x11` | SVGX structured stream, §2 |
| `0x91` | error (large-window Brotli is not accepted) |
| any other of the 254 values | whole-file standard Brotli stream; strict decode of all of `F` |

RFC 7932 §9.1: the low seven bits `0010001` (WBITS selector `1`,`000`,`001`) are invalid in a
standard stream, so no valid standard stream begins with `0x11` or `0x91`; the two branches are
disjoint. Recommended file extension for the union: `.svgx`; format identifier `svgx-1`.

The encoder (§13) emits `C = min(B, S)` where `B` is the raw Brotli stream of the whole source and
`S` the complete structured stream (∞ when the file has no modeled block). Ties choose `B`.

## 2. Structured header (normative, 60 bytes)

| Off | Size | Field | Rule |
|---:|---:|---|---|
| 0 | 1 | marker | `0x11` |
| 1 | 1 | version | `0x01` |
| 2 | 1 | profile | `1`=D, `2`=P, `3`=I, `4`=U, `5`=G |
| 3 | 1 | flags | `0x00` |
| 4 | 8 | source_length | ≤ 2^30 |
| 12 | 4 | crc32 | CRC-32/ISO-HDLC of the original bytes |
| 16 | 4 | literal_len | length of §3 literal section |
| 20 | 4 | schedule_len | length of §4 schedule section |
| 24 | 4 | geometry_len | `= ceil(geometry_bits/8)` |
| 28 | 8 | geometry_bits | valid bits of §6 |
| 36 | 4 | spelling_len | `= ceil(spelling_bits/8)`; style field |
| 40 | 8 | spelling_bits | valid bits of §9; style field |
| 48 | 4 | escape_len | style field |
| 52 | 4 | escape_count | number of escaped descriptors; style field |
| 56 | 4 | hole_count | `= 16 × total blocks` |

Sections follow immediately in this order: literals, schedule, geometry, spelling, escapes.
`len(F) = 60 + literal_len + schedule_len + geometry_len + spelling_len + escape_len` exactly.
Padding bits in the last byte of geometry and spelling are zero.
CRC-32/ISO-HDLC: reflected polynomial `0xEDB88320`, init `0xFFFFFFFF`, final xor `0xFFFFFFFF`
(check value of ASCII `123456789` is `0xCBF43926`); stored little-endian.

The fixed header after zeroing the four style fields is `H(0)`; its size is 60 bytes for every
profile. Literal, schedule and geometry sections are byte-identical across all five profiles; the
escape section is byte-identical across I, U and G.

## 3. Literal section (normative)

`Brotli(U)` where `U` is the concatenation of every untouched source byte (all bytes except the
hole lexemes), in source order. Always present (Brotli of an empty `U` is a valid 1-byte stream).

## 4. Schedule section (normative)

`Brotli(SCHED)` where `SCHED` is a sequence of LEB128 values, fully consumed:

```
n_paths
repeat n_paths times:  start_delta, u_len, K, n_blocks
repeat hole_count times: gap
```

Path `j` occupies the end-exclusive span `[start_j, end_j)` of `U` with
`start_0 = start_delta_0`, `start_j = end_{j-1} + start_delta_j`, `end_j = start_j + u_len_j`.
Constraints: `end_j ≤ |U|`, `0 ≤ K ≤ 18`, `n_blocks ≥ 1`, `16·Σ n_blocks = hole_count`.
Hole `i` is inserted before byte `U[pos_i]`, `pos_0 = gap_0`, `pos_i = pos_{i-1} + gap_i`
(zero gaps make adjacent holes); `pos_{last} ≤ |U|`. Holes are assigned to paths by ordinal: path
`j` owns the next `16·n_blocks_j` holes, which removes any ambiguity where offsets coincide. Each
owned hole satisfies `start_j ≤ pos_i ≤ end_j`. The reconstructed source is
`U[0:pos_0] ‖ lex_0 ‖ U[pos_0:pos_1] ‖ lex_1 ‖ … ‖ lex_last ‖ U[pos_last:]` (the unconsumed suffix
is appended once). Fields are bounded by `< 2^32` (gaps, lengths, counts).

## 5. Path grammar (normative; shared by encoder and decoders)

Bytes are ASCII. `wsp ∈ {0x20,0x09,0x0A,0x0D}`, `comma = 0x2C`,
`comma-wsp := (wsp+ comma? wsp*) | (comma wsp*)`. The SVG 1.1 path BNF is used:

```
path        := wsp* (moveto-group (wsp* moveto-group)*)? wsp*
moveto-group:= moveto (wsp* drawto)*
moveto      := [Mm] wsp* pair (comma-wsp? pair)*      ; extra pairs are implicit L/l
drawto      := [Zz] | [Ll] wsp* pair (comma-wsp? pair)*
             | [Hh] wsp* num (comma-wsp? num)*   | [Vv] wsp* num (comma-wsp? num)*
             | [Cc] wsp* pair c? pair c? pair (comma-wsp? pair c? pair c? pair)*
             | [Ss] wsp* pair c? pair (…)*       | [Qq] wsp* pair c? pair (…)*
             | [Tt] wsp* pair (comma-wsp? pair)*
             | [Aa] wsp* arc (comma-wsp? arc)*
pair        := num comma-wsp? num                 ; c? above = comma-wsp?
arc         := nonneg comma-wsp? nonneg comma-wsp? num comma-wsp flag comma-wsp? flag comma-wsp? pair
flag        := "0" | "1"
num         := sign? mantissa exponent?           ; nonneg has no sign
mantissa    := digits | digits "." digits? | "." digits
exponent    := [eE] sign? digits                  ; only consumed when a digit follows
```

Numbers are scanned greedily (`1.5.5` is `1.5`,`.5`; `1e5.5` is `1e5`,`.5`). A path must begin with
`M`/`m`. A first `m` is absolute (current point starts at (0,0)). Closepath sets the current point to
the subpath start; a command following `Z` other than `M`/`m` continues from that point.

**Current point.** Updated by the endpoint of every command (M, L, implicit L, H, V, C, S, Q, T, A;
relative forms add to the current point; H/V change one coordinate).

**Cubic runs and blocks.** A *cubic group* is one `pair pair pair` argument of `C` or `c`. A run is
a maximal sequence of consecutive cubic groups not interrupted by any other command (a switch
between `C` and `c` does not interrupt; any of M, Z, L, implicit L, H, V, S, Q, T, A does). A run of
`n` groups yields `floor(n/4)` blocks, taken from its first group; the remainder stays literal.

**Geometry-relevant tokens.** Every endpoint coordinate token of every command, plus the four
control-coordinate tokens (`x1 y1 x2 y2`) of every cubic group inside a block. Other tokens (arc
radii/rotation/flags, S/Q control points, controls of remainder groups) are not geometry-relevant.

**Holes.** In a modeled path, exactly the control-coordinate tokens of block groups are holes.
A decoder parses the masked span with each hole as an atomic number token whose boundaries are
explicit; a hole anywhere else, a missing hole, or a block count different from `n_blocks` is an
error.

## 6. Numeric descriptors and the grid (normative)

A number lexeme has a sign `s ∈ {none,'-','+'}`, mantissa digits (count `w`), optional dot, `k`
digits after the dot, optional exponent bytes `E` (`[eE][+-]?[0-9]{1,6}`, numeric value `e`; `e=0`
when absent). Bounds: `1 ≤ w ≤ 38`, `0 ≤ k ≤ w`, `k=0` without dot, ≤ 6 exponent digits, `|e| ≤ 18`,
lexeme ≤ 64 bytes. Digit counts are checked before any exponentiation. Value
`v = ±M·10^(e−k)`, `M` the mantissa digits as an integer.

Path grid: `K = max(0, max(k−e))` over the path's geometry-relevant tokens, `0 ≤ K ≤ 18`.
Grid value `X = v·10^K` (an integer). Every geometry-relevant token and every absolute coordinate
(current points and absolute control points) satisfies `|X| < 2^96`. Negative zero is a valid lexeme
(`X = 0`, sign `-`).

**Rendering a descriptor** `(s, w, k, dot, E)` at `(X, K)`: let `t = k − e − K`; if `t ≥ 0`,
`M = |X|·10^t`, else `M = |X| / 10^(−t)` which must be exact. Require `M < 10^w` and sign
compatibility (`X<0 ⇒ s='-'`, `X>0 ⇒ s≠'-'`, `X=0` any). Output: `s`, then `M` left-padded with zeros
to `w` digits with a dot inserted before the last `k` digits when `dot` (so `k=w` gives `.5`, `k=0`
with dot gives `5.`), then `E`. Otherwise the descriptor is *inapplicable*.

**Descriptor serialization** (escape section, D arm): byte0 = `sign` (bits 0–1: 0 none, 1 `-`,
2 `+`) | `dot`<<2 | `has_exp`<<3 (bits 4–7 zero); byte1 = `w`; byte2 = `k`; when `has_exp`:
byte3 = `len(E)` (2…8) followed by the bytes of `E`. All bounds above are validated.

## 7. Geometry section (normative)

Blocks are numbered in file order. Block `b` has segments `s = 0..3` with absolute grid points
`P0_s, P1_s, P2_s, P3_s` (path grid of its own path), `P0_{s+1} = P3_s`. Junctions
`J_s = P0_s (s=0..3)`, `J_4 = P3_3` come from literal tokens. Vectors: `c_s = P3_s − P0_s`,
`h0_s = P1_s − P0_s`, `h1_s = P3_s − P2_s`. Rounding `R(n/d)` (`d > 0`): `q = floor(n/d)`,
`r = n − q·d`; `q+1` if `2r > d`; `q + (q mod 2)` if `2r = d`; else `q`.

**Bound.** Every intermediate integer listed below must satisfy `|x| < 2^126`; a computation that
violates it makes that predictor unavailable (the encoder never selects it; a decoder rejects a
stream that does).

| Mode | Prediction |
|---|---|
| `00` | `0` for all 8 handle vectors |
| `01` | `h0_s, h1_s ← R(c_s/3)` componentwise |
| `10` | `h0_0 ← R(c_0/3)`, `h0_s ← h1_{s−1}` (actual) for `s ≥ 1`; `h1_s ← R(n/D)` per component with `D = c·c`, `n_x = 2c_x(c·h0_s) − h0_{s,x}·D` (actual `h0_s`), and `0` when `D = 0`. Bounded: `c·h0`, `D`, each product, `n`. |
| `11` | reference block at backward distance `d` (1 = previous block), `d ≤ min(4096, b)`. Triple `(a,β,γ)`, `a<β<γ` over junction indices `0..4`, maximizing `|det(J_β−J_a, J_γ−J_a)|` of the **target**, ties lexicographic; if the maximum is 0 the mode is unavailable. `T = [J_β−J_a, J_γ−J_a]` (target), `Q` = same indices of the reference; `det(Q) = 0` is unavailable. For each reference handle `h` (same slot): `u = adj(Q)·h`, `n = T·u`, prediction `R(n/det Q)` with sign of numerator and denominator flipped when `det Q < 0`. Bounded: both determinant products and determinants, every product and sum in `u` and `n`. |

Residuals `r = actual − prediction` in order `h0x,h0y,h1x,h1y` for `s = 0..3` (16 scalars), each
bounded like every other intermediate (`|r| < 2^126`); zigzag `z = 2r (r ≥ 0)`, `z = −2r−1 (r < 0)`,
hence `z < 2^127`. A decoder rejects `z ≥ 2^127` and `|r| ≥ 2^126`.

**Block record:** `mode` (2 bits), if `11`: LEB128(`d−1`) octets each written as 8 bits, `p` (4 bits,
0…15), then per scalar `gamma(floor(z/2^p)+1)` followed by the `p` low bits of `z`.
`gamma(n)`: `floor(log2 n)` zero bits then the binary digits of `n` (≤ 127 leading zeros accepted).
After the stated number of blocks the reader position must equal `geometry_bits`.
Reconstruction: `h = prediction + r`, `P1 = P0 + h0`, `P2 = P3 − h1`; absolute coordinates must
satisfy `|·| < 2^96`. Token values: `C` → `X = P1.x, P1.y, P2.x, P2.y`; `c` → `X = (P1−P0), (P2−P0)`.
Every decoded block (any mode) is appended to the reference window in decoder order.

## 8. Roles and the spelling rule family (normative)

Holes are spelled in hole order. Role `ρ = 4·rel + 2·second + y` (`rel`: lowercase `c`;
`second`: control point P2; `y`: y component), giving eight roles.

With `v = X/10^K`, `fixed(d, L)` applies iff `|v|·10^d` is an integer `N`; it writes `-` if `X<0`, the
decimal digits of `N` left-padded to at least `d+1` digits, and a dot before the last `d` digits when
`d > 0`. Variant `S` removes a single leading `0` of the integer part when `0 < |v| < 1`.
`shortest(V)` is `fixed(d*, V)` with the smallest `d* ≥ 0` that applies. Zero is unsigned.

| ID | Rule | | ID | Rule |
|---|---|---|---|---|
| 1 | fixed(0, L) | | 5 | fixed(4, L) |
| 2 | fixed(1, L) | | 6 | shortest(L) |
| 3 | fixed(2, L) | | 7 | shortest(S) |
| 4 | fixed(3, L) | | 8 | fixed(2, S) |

## 9. Spelling section (normative)

Empty (`spelling_bits = 0`) for D and whenever `hole_count = 0`; otherwise one arithmetic-coded
stream (§10) holding every coded symbol of the file. State resets at file start.

**Rule weights (I, U, G).** Per role nine weights `w[1..8]`, `w[esc]`, all initially 1. For each hole:
`A` = applicable rule IDs (ascending). After the actual lexeme `y` is known: `Mt = {f ∈ A : f(v) = y}`;
if `Mt ≠ ∅` add 1 to `w[f]` for every `f ∈ Mt`, else add 1 to `w[esc]`; then, if the role's total of all
nine weights is ≥ 16384, set every one of the nine to `(w+1) div 2`. Other roles are untouched.

| Profile | Alphabet (cumulative order) and frequencies | Coded symbol |
|---|---|---|
| I | each `f ∈ A` (ascending) with `w[f]`, then escape `w[esc]` | highest-weight `f ∈ Mt` (ties: smallest ID); escape if `Mt = ∅` |
| U | groups of `A` with identical output, ordered by smallest member ID, frequency `max w[f]`; then escape | the group whose output is `y`; else escape |
| G | same groups, frequency `Σ w[f]`; then escape | same as U |

**P (previous descriptor).** Per role `prev` (initially none) and two flag weights `[match, escape]`
(initially 1,1; +1 to the observed symbol; halve with `(w+1) div 2` when their total ≥ 16384). If
`prev` is none, or `prev` is inapplicable at `(X,K)`, the event is an implicit escape (no symbol).
Otherwise a binary symbol is coded (order: match, escape). After each hole `prev` = descriptor of
the actual lexeme.

**Escapes.** An escape takes the next descriptor of the escape section and renders it at `(X,K)`; it
must be applicable. In I/U/G its output must differ from every applicable rule output; in P it must
differ from the `prev` rendering when `prev` was applicable. `escape_count` must equal the number of
escapes, and the descriptor stream must be consumed exactly.

**D.** The escape section holds the descriptors of all holes (`escape_count = hole_count`).

**Escape section.** `Brotli(concatenated descriptors)` when `escape_count > 0`; empty otherwise.

## 10. Arithmetic coder (normative)

Witten–Neal–Cleary integer coder, 32-bit code values: `TOP = 2^32−1`, `HALF = 2^31`,
`Q1 = 2^30`, `Q3 = 3·2^30`. Totals `T ≤ 2^16`, every coded frequency ≥ 1, cumulative symbol order as
listed in §9. Intermediates use 64-bit unsigned arithmetic.

Encode `[cl, ch)` of `T`: `range = high−low+1; high = low + range·ch div T − 1; low = low + range·cl div T`;
then loop: `high < HALF` → emit 0 (plus pending 1s); `low ≥ HALF` → emit 1 (plus pending 0s),
`low −= HALF, high −= HALF`; `low ≥ Q1 ∧ high < Q3` → `pending += 1`, `low −= Q1, high −= Q1`;
else stop; after each case `low = 2low, high = 2high+1`. Finish: `pending += 1`; emit 0 (plus pending
1s) if `low < Q1`, else 1 (plus pending 0s). `spelling_bits` = number of emitted bits.

Decode: `value` = first 32 bits (bits at or beyond `spelling_bits` read as 0). Symbol: `range` as
above, `cum = ((value−low+1)·T − 1) div range`, select `cl ≤ cum < ch`, update `low, high` as the
encoder, normalize identically while transforming `value` (`−HALF`, `−Q1`) and shifting in the next
bit. Termination check after the last symbol: with `S` the number of shifts performed,
`spelling_bits = S + 2` and `value = Q1` if `low < Q1`, else `value = HALF`.

## 11. Decoder validation summary (normative)

Reject: empty input; `0x91`; non-strict Brotli in any section; bad marker/version/profile/flags;
inconsistent lengths, padding, bit counts or counts; schedule violations; masked-grammar mismatch;
literal geometry token off-grid or out of bounds; out-of-window or non-canonical distance; unavailable
predictor; residual or coordinate out of bounds; leftover bits; non-canonical spelling termination;
escape/descriptor violations; length or CRC mismatch of the reconstruction.

## 12. Reconstruction (normative)

1. Parse header, decode literal and schedule sections. 2. For each path, parse its masked span,
recover junctions and block structure. 3. Decode all geometry records (window across the file).
4. Compute `X` for every hole. 5. Decode lexemes in hole order (§9). 6. Interleave `U` and lexemes
(§4). 7. Check length and CRC.

## 13. Encoder behaviour (encoder; frozen)

1. Inputs over 2^30 bytes: raw Brotli only.
2. Encoding: UTF-8 BOM accepted; UTF-16/32 BOM or `\0<\0?` patterns → unmodeled. An XML
   declaration encoding must be one of `utf-8, utf8, us-ascii, ascii, iso-8859-1, latin1,
   iso-8859-15, windows-1252` (case-insensitive) else unmodeled. UTF-8 (declared or default) input
   must be valid UTF-8, else unmodeled.
3. Byte-span XML scan: comments, CDATA, PIs, DOCTYPE (an internal subset containing `<!ENTITY` or
   `<!ATTLIST` makes the file unmodeled; external entities are never resolved), start/end tags with
   balance checks, quoted attributes, duplicate attribute detection, namespace declarations
   (a namespace value containing `&` makes the file unmodeled). Any malformation → unmodeled.
4. Modeled attribute: unprefixed `d` of an element whose expanded name is
   `{http://www.w3.org/2000/svg}path`. Values containing `&`, longer than 16 MiB, failing §5, with no
   block, or violating §6 bounds stay literal (counted by reason).
5. Mode search per block: modes `00, 01, 10` and, for `11`, candidates among the last 4096 blocks
   ranked by the IEEE-754 double sum of squared differences between the target's and the
   candidate's eight control points expressed in their own triple's affine coordinates
   (`T⁻¹(P−J_a)`, `Q⁻¹(P'−J'_a)`), ties by smaller distance; walk this order, skip overflowing
   candidates, evaluate exactly the first eight usable ones. Cost = exact bits for every `p ∈ 0..15`;
   minimal total wins, ties by mode, distance, `p`. Encoding is single-threaded per file, so output
   is independent of worker count.
6. All profiles reuse identical literal, schedule and geometry bytes; `--force-structured` emits the
   structured stream even when larger than raw Brotli (used for testing and forced-structured
   accounting).

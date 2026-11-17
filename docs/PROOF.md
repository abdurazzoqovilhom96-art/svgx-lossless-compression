# Proof notes (SVGX v1)

## 1. Reconstruction

Let the source be `S`. The encoder selects hole spans `h_1 < … < h_n` (control-coordinate number
tokens of modeled blocks; disjoint, ordered). `U` is `S` with every hole span removed, and `pos_i` is
the number of `U` bytes preceding `h_i` (FORMAT §4). Then by construction

`S = U[0:pos_1] ‖ S[h_1] ‖ U[pos_1:pos_2] ‖ … ‖ S[h_n] ‖ U[pos_n:]`.

The decoder obtains `U` and every `pos_i` exactly (Brotli is lossless; LEB128 is canonical). It
therefore suffices that it recovers each lexeme `S[h_i]` exactly.

*Geometry.* Junctions come only from literal endpoint tokens (holes never update the current point,
FORMAT §5), so the masked parse yields the same command structure, blocks and junctions as the
source parse: number tokens of the source are either wholly holes or wholly literal, and the greedy
scan of a literal token is unchanged by an explicit boundary at the position where the source scan
already stopped. Every literal geometry-relevant token is on the grid `10^-K` (definition of `K`), so
`J` is exact. The geometry records store `r = h − pred(h)` where `pred` is a deterministic function of
already-decoded data (junctions, previous handles of the block, earlier blocks, the stored distance),
evaluated with identical bounded integer arithmetic in both decoders; hence `h = pred + r` exactly,
`P1 = P0 + h0`, `P2 = P3 − h1`, and the source-coordinate value `X` of every hole (absolute or
relative to `P0`) is exact.

*Spelling.* Given `(X, K)` and the identical causal state, the decoder forms the same alphabet as the
encoder; the arithmetic decoder returns the encoder's symbol (WNC correctness with totals `< 2^16`
and range `> 2^30`, so every frequency gets a non-empty sub-interval). A rule symbol yields that
rule's exact output, which by the encoder's choice equals `S[h_i]`; an escape yields the rendering
of the stored descriptor of `S[h_i]`, which reproduces it exactly (descriptor fields are read from the
lexeme; `M = |X|·10^(k−e−K)` equals its mantissa digits; padding to `w`, the dot position, sign and
exponent bytes are restored verbatim). The state update depends only on the decoded bytes, so the
next step starts from the same state (induction over holes). With all lexemes restored, the
interleaving above returns `S`; CRC-32 and length provide an end-to-end check.

## 2. Disjoint outer branches

Structured streams begin with `0x11`. A standard Brotli stream's first byte encodes WBITS in its low
bits; RFC 7932 §9.1 makes the 7-bit pattern `0010001` invalid, so no standard stream begins with
`0x11` or `0x91`. The decoder dispatches on the first octet; `0x91` is rejected. Hence each compressed
file has exactly one interpretation, and the emitted length `C = min(B, S)` (ties → raw) satisfies
`C ≤ B`.

## 3. Ideal code length: G versus I

Fix a token with value `v`, role state `w`, eligible (applicable) rule set `A`, and
`W = w_esc + Σ_{f∈A} w_f`. Both I and G use the same denominator `W`. For an outcome `y` matched by
`M(y) = {f ∈ A : f(v) = y} ≠ ∅`, I codes the single highest-weight index, probability
`max_{f∈M(y)} w_f / W`; G codes the group, probability `Σ_{f∈M(y)} w_f / W`. The ideal saving of G
over I on that token is `log2(Σ_{M(y)} w_f / max_{M(y)} w_f) ≥ 0` bits, with equality iff `|M(y)| = 1`
(or all other matching weights are zero, impossible since weights are ≥ 1). For an escape both assign
`w_esc / W`. The update rule depends only on the decoded bytes, so I and G traverse identical states;
by induction over tokens, G's ideal total is never larger than I's. Actual streams add arithmetic-coder
termination, padding and fixed header fields, which are equal in width but not necessarily equal in
value.

**G versus U.** U uses group frequency `max` and denominator `w_esc + Σ_groups max`, G uses `Σ` and
`W`. Neither dominates: in the reduced fixture (fixed1, shortest-L, fixed2, escape, weights 1 at
`v = 1/2`) G gives `0.5` probability 1/2 vs U 1/3 (G wins one ideal bit-fraction) but gives `0.50`
probability 1/4 vs U 1/3 (G loses). The whole-file comparison is empirical and reported as measured.
Duplicating a rule would change G's probabilities without adding a spelling; the rule set is frozen.

## 4. Accounting invariants

`O_i = min(B_i, H(0) + L_i + R_i)` where `H(0) = 60` bytes (fixed header with style fields zeroed),
`L_i` = literal + schedule section lengths, `R_i` = geometry section length. Every structured stream
of file `i` has length `60 + L_i + R_i + spelling + escapes ≥ H(0) + L_i + R_i`, and the raw branch
has length `B_i`, so `O_i ≤ C_i` for all five arms. The ledger verifies `C_i ≤ B_i`, raw fallback bytes
equal to the independent `brotli.exe` stream, strict `C_i < B_i` whenever the structured branch is
emitted, `O_i ≤ C_i`, and exact reconciliation of header + sections to the file length.

## 5. Bounded arithmetic agreement

Rust evaluates every listed intermediate with checked `i128` operations followed by `|x| < 2^126`;
Python evaluates exact integers followed by the same comparison. A Rust overflow implies the exact
magnitude exceeds `2^127 − 1 > 2^126`, which Python rejects too; otherwise both compute the same exact
value. Hence both decoders accept exactly the same predictors and produce identical predictions.

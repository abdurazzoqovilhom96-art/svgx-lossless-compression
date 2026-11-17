# METHOD_SPEC — SVGX v1 arms, pipeline, accounting and contribution map

Sources: `docs/FORMAT.md` (frozen, sha256 8052ec24…), `docs/PROOF.md` (bb055395…), `docs/PROTOCOL.md` (1bfe1956…),
`config/study.toml` (265406d3…), codec `codec/src/*.rs`, binary `svgx.exe` (07a6841c…), build `build-fb5b391323df`.
All 53 bound files are unchanged since the freeze of 2026-11-13T17:38:03Z (`derived/a04_results.json`).

## 1. What the codec does (common to all five arms)

1. **Outer union.** The output is `C = min(B, S)`, where `B` is the raw Brotli-11 stream of the whole file and
   `S` is the structured stream. Ties are emitted as `B`.
   - Brotli: Google 1.2.1, quality 11, lgwin 22, compiled identically into the codec and into `brotli.exe`.
   - `S` is the complete structured stream; `S = ∞` when the file has no modeled block.
   - Mode signalling costs **0 bytes**. A structured stream starts with `0x11`; RFC 7932 §9.1 makes `0x11` and
     `0x91` impossible first bytes of a standard Brotli stream (FORMAT §1, PROOF §2).
   - No file extension or external metadata is used.
2. **What is modeled.**
   - Only the unprefixed `d` attribute of SVG-namespace `<path>` elements is modeled.
   - Within it, only the 4 control-point coordinates of cubic Bézier groups that lie inside blocks of 4 consecutive
     `C/c` groups.
   - These tokens become *holes*. Everything else stays in the literal stream `U`.
3. **Sections of `S`.** They appear in this order:
   - 60-byte header;
   - literals = Brotli(U);
   - schedule = Brotli(LEB128 positions);
   - geometry (bit-packed residuals of predicted handle vectors);
   - spelling (arithmetic-coded);
   - escapes = Brotli(descriptors).
4. **Geometry.** Handle vectors are predicted by one of four modes (zero, chord/3, smooth continuation, affine copy
   from one of the last 4096 blocks). The integer residual is coded with an adaptive Golomb-gamma code.
   All arithmetic is exact and bounded (|x| < 2^126).
5. **Spelling.** The decoder knows the exact value `X` of each hole before its bytes. The *spelling* model restores
   the exact lexical form (sign, digits, dot, exponent) given `X`. **The five arms differ only here.**

## 2. Variant map (A05)

| Arm | Transformation | Spelling of a hole given its exact value | Fallback | Core | Arm-specific overhead | Role in the study |
|---|---|---|---|---|---|---|
| **D** | §1 (shared) | none: every lexeme's descriptor `(sign,w,k,dot,E)` is stored explicitly in the Brotli-compressed escape section | raw Brotli if not smaller | Brotli-11 + bit-packed geometry | escapes = all holes; spelling section empty | internal control: explicit descriptors (analogue of the closest genomic byte-exact descriptor approach) |
| **P** | §1 | per role, the previous descriptor is re-rendered at `X`; a binary match/escape flag is arithmetic-coded | same | same | flags + escapes for misses | internal control: previous-style predictor |
| **I** | §1 | frozen family of 8 formatting rules; the coder sends the identity of the highest-weight rule that reproduces the bytes (else escape) | same | same | rule symbols + escapes | internal ablation: rule identities, no grouping |
| **U** | §1 | same 8 rules; rules whose outputs coincide are **grouped**; group frequency = max of member weights | same | same | group symbols + escapes | internal ablation: grouping with max |
| **G** | §1 | same 8 rules, grouped; group frequency = **sum** of member weights | same | same | group symbols + escapes | primary arm (frozen `primary_profile = "G"`) |

None of D/P/I/U/G is an external or previously published method. All five are components of this study. The literal,
schedule and geometry sections are byte-identical across the five arms for every file, and the escape section is
byte-identical across I/U/G. Both properties were verified by section hash for all 1,324 files.
C\* = P was chosen on the pilot by the frozen rule "smaller pilot aggregate of D/P; ties → P".

## 3. Contribution map (confirmation split, 1,076 files; exact byte totals)

Ceiling `O` = `min(B, 60 + literals + schedule + geometry)`: the size if spelling and escapes cost nothing, within
*this* container and geometry model (FORMAT/PROOF §4). It is not a bound for other methods.

| Step | Contrast (A → C) | Bytes saved | Gain % of ΣA | What it isolates |
|---|---|---:|---:|---|
| Whole system | Brotli-11 → G | 543,876 | 1.3655 | geometry modeling + selection + spelling model, end to end |
| Free-spelling bound | Brotli-11 → O | 555,107 | 1.3937 | geometry/literal split with zero spelling cost |
| Explicit descriptors | Brotli-11 → D | 439,265 | 1.1029 | geometry with the simplest exact spelling |
| Spelling model, total | D → G | 104,611 | 0.2656 | value-conditioned spelling vs explicit descriptors |
| Rule identities only | D → I | −7,966 | −0.0202 (I larger) | rule IDs without grouping do not beat descriptors in total |
| **Grouping identical outputs** | I → U | 107,847 | 0.2737 | the output-grouping mechanism (max weights) |
| Sum vs max weights | U → G | 4,730 | 0.0120 | G-specific aggregation (the design's named mechanism) |
| Previous-descriptor control | D → P | 6,184 | 0.0157 | |

Ceiling realised by each arm: D 79.1 %, P 80.2 %, I 77.7 %, U 97.1 %, **G 98.0 %**. G closes 90.3 % of D's
spelling gap to the ceiling (`derived/a03_results.json`).

**Problem → control → evidence triples**

1. **Generic compressors cannot exploit exact Bézier geometry.**
   - Component: geometry predictor + structured branch.
   - Control: raw Brotli-11 (identical library and parameters).
   - Evidence: whole-system 1.3655 %, ceiling 1.3937 %. Forced-structured accounting shows the selection is
     necessary: gross gain 543,876 B and gross loss 1,259,778 B over 362 files with a structured stream, a net
     −715,902 B if `S` were always emitted.
2. **Exact numerals must be restored from values cheaply.**
   - Component: rule-family spelling.
   - Control: D (explicit descriptors).
   - Evidence: D → G 0.2656 %. The spelling overhead falls from 115,842 B to 11,231 B above the ceiling.
3. **Several rules emit identical bytes, so rule identities waste code space.**
   - Component: output grouping.
   - Control: I (rule identities), from which U and G differ only by grouping.
   - Evidence: I → U 0.2737 %; PROOF §3 gives G ≤ I in ideal code length per token.
4. **Pooling the weights of grouped rules.**
   - Component: sum (G) vs max (U).
   - Control: U.
   - Evidence: 0.0120 %; Bonferroni interval [0.0013, 0.0612] %. Positive but practically negligible.

## 4. Losslessness (A04)

- **Definition: byte-exact.** `decode(encode(x)) == x` on the original byte string, checked by SHA-256 of the
  restored bytes. Visual or XML equivalence is not accepted.
- **Coverage in the frozen run:**
  - Files and arms: every file (1,324) × every arm (5) × final and forced-structured streams.
  - Decoders: the native Rust decoder and the independent Python reference decoder, each in a separate process.
  - Recomputation: the audit re-derived this from the ledger fields rather than from the `verified` flag.
- **Raw branch identity.** The raw branch is byte-identical to the independent `brotli.exe` stream for 1,324/1,324
  files.
- **Audit re-check, 2026-11-15.**
  - All 14,564 stored streams hash to the ledger values.
  - The 39 structured G streams of the confirmation split were re-decoded with the frozen Python reference decoder:
    39/39 restored SHA-256 equal to the originals (39 new codec jobs).
- **Scope of the guarantee.**
  - Byte-exactness is proven by construction (PROOF §1) and verified on the measured corpus and synthetic fixtures
    (106 pytest + 20 cargo tests at readiness).
  - "Never larger than Brotli-11 (q11, lgwin22)" holds by construction for this container: `C = min(B, S)`, 0-byte
    mode flag.
  - It is not a statement about other Brotli settings or other compressors.

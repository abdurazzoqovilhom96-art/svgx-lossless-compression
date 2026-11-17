# SVGX-REV1 — protocol for the revision experiments B1–B3

Status: written and frozen **before** any REV1 measurement on the confirmation split. The freeze record
`state/freeze_rev1.json` hashes this file, every REV1 script, the configuration and the tools. The approval record
`state/approval_rev1.json` is bound to the SHA-256 of that freeze record. Every experiment script refuses to touch
the confirmation split without it and exits with code 4.

This protocol is internal. It is not publicly registered. A public timestamp, for example by pushing it to the
GitHub repository, is left to the authors.

## 1. Data and status of the analysis

- **Base study.** Design `SVGX-2026-11-A`, run `20261114_050438_SVGX-2026-11-A`. The ledger, frozen binary and
  reference decoder are used read-only; their SHA-256 values are checked by every script (`common.FROZEN_HASHES`).
- **Data: variant A.** The frozen confirmation split: 1,076 files, 55 families, 362 files with a structured
  stream. These data were analysed before for another question. Every REV1 result is therefore a *pre-specified
  re-analysis of previously analysed data* and must be labelled as such. Nothing is tuned on these data.
- **Calibration** (paq8px level, zstd dictionary) uses the pilot split only (248 files).
- **Licence sensitivity.** Each estimand is also reported without the 37 files listed in
  `config/license_sensitivity_exclude.csv`.

## 2. Code changes and the regression gate R0

`SVG_EXPERIMENT_REV1` is a copy of the frozen project. Only two things are added to the codec:

- `--modes L`, which restricts the geometry encoder to a nested set of prediction modes. The default is all modes.
- `svgx bench`, an in-process timing command.

The format, the decoders and the default behaviour are unchanged.

**R0** must pass before B1–B3 run. The REV1 build, at default settings, must reproduce the frozen run byte for byte:

- for every file, `raw.br` matches the ledger `baseline_sha256`;
- for every profile D/P/I/U/G, the final and forced streams match `final_sha256` and `forced_sha256`, and the
  absence of a forced stream also matches;
- `stats.json` is equal to the ledger `stats` object.

On the synthetic fixtures the build must equal the frozen binary and `expected.json`. One mismatch stops the study.

Results already obtained during preparation:

| Check | Result |
|---|---|
| Fixtures | 30/30 equal |
| Pilot | 248/248 files equal (all streams and stats) |
| `cargo test` | 21 passed |
| `pytest` | 121 passed (106 original + 15 REV1) |

## 3. Monotonicity lemma and automatic invariants

Take nested mode sets M ⊆ M′. For every file, S(M′) ≤ S(M) and C(M′) ≤ C(M). The reasons:

1. The prediction window, the junction triples and the affine candidates depend only on the decoded data, and
   these are identical under every mode set.
2. Each block is coded with the cheapest allowed mode.
3. C = min(B, S).

Hence every ablation step is ≥ 0. Only magnitudes are estimated; there are no sign tests.

Checked per file; any violation is a defect and stops the study:

- C_F ≤ C_M010 ≤ C_M01 ≤ C_D0 ≤ B, and the same chain for the forced lengths S;
- C = min(B, S), with ties going to raw;
- literal, schedule, spelling and escape sections are byte-identical across mode sets;
- no disallowed mode is used;
- H ≤ P(x), and S_P reconciles with its sections;
- every new stream decodes to the original bytes. Codec streams are checked with both decoders; T and Z sections
  are encoded and decoded in Python; paq8px, zstd and Brotli streams are decoded with their own tools.

## 4. Experiments

### B1 — contribution of geometric prediction

| Arm | Definition |
|---|---|
| B | raw Brotli-11 (lgwin 22), from the ledger |
| T | Separation only. Hole lexemes are joined by one space and stored as one extra Brotli stream (the codec's own Brotli). S_T = 60 + \|Br(U)\| + \|Br(schedule)\| + \|Br(holes_text)\| |
| Z | Values as written. Hole values X are zig-zag mapped and coded with an order-p exp-Golomb code, p ∈ 0..15 per block of 16 holes (4 bits); no prediction. The G spelling and escape sections are unchanged. S_Z = 60 + \|Br(U)\| + \|Br(schedule)\| + ⌈bits_Z/8⌉ + \|spelling_G\| + \|escapes_G\| |
| D0 / M01 / M010 | codec with `--modes 00` / `00,01` / `00,01,10` |
| F | all modes; this is the frozen G output |

The final output of every arm is C = min(B, S). Files without a modelled block have C = B in every arm.

Estimands, all ratios of sums:

- **Primary (confirmatory):** R1 = (ΣC_D0 − ΣC_F)/(ΣB − ΣC_F) ∈ [0, 1].
- **Secondary:**
  - R11 = (ΣC_M010 − ΣC_F)/(ΣB − ΣC_F);
  - the steps π over ΣB along the chain B → D0 → M01 → M010 → F;
  - Gain(F vs T) and Gain(F vs Z);
  - geometry bits per hole for each arm (diagnostic).

### B2 — strong comparators and a strong back end

**paq8px v217.** Official Windows x64 release archive (`paq8px_v217_windows_x64.7z`); its SHA-256 matched the
GitHub release digest. The binary was built on 2026-09-28, ≥ 14 days old. No flags; single thread. Fixed member
name `input.svg`; single-file archives store no name.

- *Level rule (fixed before calibration):* the highest level whose peak committed memory (Job Object
  `PeakJobMemoryUsed`) is ≤ 2³³ bytes (8 GiB) on every pilot calibration file. Calibration files: five plain files
  at size quantiles 0.50–0.98, the three smallest base64 files and the largest base64 file ≤ 1 MiB.
- *Calibration results:*

  | Level | Peak memory | Within cap? |
  |---|---|---|
  | -8 | 2,560 MiB | yes |
  | -9 | 4,428 MiB | yes |
  | -10 | 7,909 MiB | yes |
  | -11 | 14,047 MiB | no |

  → **level 10.**
- *Disclosure:* 7,909 MiB is 8.29 × 10⁹ bytes. If "8 GB" were read as 8 × 10⁹ bytes, level 9 would have been
  chosen. The binary reading (2³³) was fixed in the code before the calibration ran.
- *Parallelism:* workers = ⌊24 GiB / 7,909 MiB⌋ = 3. If memory or time limits are exceeded, only the parallelism is
  reduced; the level never changes.
- Every archive must begin with `paq8px`. Its first byte, 0x70, can never be the SVGX marker 0x11, so the hybrid
  needs 0 discrimination bytes. This is checked on every archive.

**Hybrid.** S_P = |S_G| − |Br(U)| + |P(U)|, where U is the literal stream of the frozen forced G stream; the other
sections are unchanged. H = min(P(x), S_P) on the 362 files with a forced stream, and H = P(x) on the others.
H is a measured container that is not shipped. It is decodable because each section is decoded independently:
P(U) by paq8px, the other sections by the R0-verified decoder.

**zstd 1.5.7 with dictionary.** Command: `-19 --single-thread -D config/zstd_pilot.dict`. The dictionary was
trained once on the 248 pilot files (`--train`, default fastcover, 112,640 bytes, SHA-256 `6dbfebad…`). Results are
reported both without and with the dictionary amortised over the files, i.e. |dict|/N per file.

**Brotli 1.2.1.**

- `-q 11` with the CLI default window, which is auto-sized to the file and ≤ 24.
- `-q 11 --large_window=30`.
- *Deviation from the plan text (`--large_window=24`):* 24 is the maximum standard window. Every corpus file is
  < 16 MiB (largest 13.6 MB), so a window of 24 adds nothing, and the large-window arm uses 30.

**cmix.** Excluded before measurement. Its documentation recommends at least 32 GB RAM; the host has 31.8 GB in
total and the protocol cap is 24 GB. No binary release exists.

Estimands:

- **Primary (confirmatory):** Gain_H = (ΣP − ΣH)/ΣP. It is ≥ 0 by construction, so only its magnitude is estimated.
- **Secondary:** Gain(G vs P), which may be negative; Gain(G vs zstd-dict), with and without amortisation;
  Gain(G vs Brotli auto); Gain(G vs Brotli large window); Gain(P vs B).

### B3 — algorithmic speed

**Sample** (`config/b3_sample.csv`, fixed before the freeze from the manifest and the frozen branch only):

- all 39 confirmation files whose frozen G output is structured;
- for each of them, the unused raw-branch file closest in log size; ties are broken by a seeded hash.

**Procedure:**

- One `svgx bench --profile G --cpu 2 --warmup 5 --repeats 31` process per file. It times four operations, all in
  memory with one Brotli build: G encode (the full `svgx encode` pipeline), G decode, raw Brotli-11 encode and raw
  Brotli decode.
- The operation order rotates per repeat. Timer: `std::time::Instant`. Correctness is checked untimed.
- File order is shuffled with a fixed seed.

**Controls:**

- Logical processor 2 is used: a P-core (EfficiencyClass 1) that is not the core of logical processor 0. Empirical
  check on a synthetic fixture: P-class median 143–158 ms, E-class 259 ms.
- HIGH priority class.
- The power scheme is set to High performance (`SCHEME_MIN`) and restored afterwards.
- No other experiment runs concurrently; B3 runs before B2.

**Estimands:**

- **Primary (confirmatory):** τ_dec = Σ_S median(G decode) / Σ_S median(raw decode).
- **Secondary:** τ_enc, the same ratios on the raw group, throughput, and within-file IQR/median.
- CLI start-up overhead is also reported. It is measured on a 1-byte input, 31 runs per method. Zero length is not
  used because XWRT crashes on it. The overhead is not subtracted.

## 5. Statistics

- **Bootstrap:** family-cluster percentile bootstrap; 50,000 resamples; numpy PCG64 with seed 20261116; quantile
  method `linear`. The same resample matrix is used for every estimand within an experiment.
- **Confirmatory family** {R1, Gain_H, τ_dec}: Bonferroni k = 3 at family coverage 99.5 %, i.e. tails 0.005/6.
- **Sensitivity:** BCa, with z0 from the bootstrap distribution and acceleration from a leave-one-family-out
  jackknife; the licence-excluded set.
- **Two-way computation:** every estimand is computed from the result rows and again from the per-file CSV, and
  the two are asserted equal. ΣB and ΣC_G are also asserted equal to the frozen ledger.

## 6. Pre-specified wording (applied mechanically to the Bonferroni bounds)

| Estimand | Condition | Wording |
|---|---|---|
| R1 | lower ≥ 0.5 | "prediction is the main source of the saving" |
| R1 | 0.25 ≤ lower < 0.5 | "prediction contributes a substantial share" |
| R1 | lower < 0.25 and estimate ≥ 0.10 | "minor share", with the alternative title |
| R1 | estimate < 0.10 | "the saving comes mainly from stream separation and integer re-coding" |
| Gain_H | lower ≥ 0.5 % | "geometric modelling retains value over a context-mixing back end" |
| Gain_H | otherwise | "no material gain over a strong back end" |
| τ_dec | upper < 1 | "faster" |
| τ_dec | lower > 1 | "slower by X×" |
| τ_dec | otherwise | "comparable" |

All results are reported, including negative ones.

## 7. Stopping rules

The study stops on any of:

- an R0 mismatch;
- an invariant violation;
- a round-trip failure, which is recorded as a defect and never dropped;
- a two-way mismatch.

Calibration choices, parameters and samples are never changed after the confirmation split has been touched.

## 8. Order, outputs and approval

Order: R0 → B1 → B3 → B2 → analysis. Start with `run_rev1.cmd`, which calls `rev1/run_all.py`.

Outputs go to `results_rev1/`: `r0/`, `b1/`, `b2/`, `b3/` (JSONL per file, resumable) and `analysis/confirmation/`.

Expected duration: R0 ≈ 3 min; B1 ≈ 10 min; B3 ≈ 1–1.5 h (78 files, 56 MB, 36 iterations of 4 operations);
B2 ≈ 4–5 h (paq8px about 9.8 KB/s on the pilot, compression and decompression, 3 workers). Total ≈ 6–7 h.

## 9. B4 (fresh family-disjoint holdout): not part of this approval

A power simulation from the frozen results (`rev1/b4_power.py`, `config/b4_power.json`) used the B4 stratum:
illustrations and maps > 64 KiB, 66 files and 32 families in confirmation; observed Gain 1.44 %. Results:

- For "lower 99.5 % bound of Gain > δ = 1 %", power stays ≤ 0.11 up to 120 families.
- For δ = 0, power is ≥ 0.99 from 20 families. But δ = 0 is nearly guaranteed by construction, since C ≤ B.

B4 as planned is therefore not informative. Any new collection needs a redesigned hypothesis and a separate
approval.

## 10. Deviations from the internal revision plan (REVISION_PLAN_UZ.md)

1. paq8px: the official release binary (digest-verified) instead of a source build.
2. Brotli large window: 30 instead of 24 (§4 B2).
3. cmix: excluded a priori (§4 B2).
4. The "8 GB" cap is read as 2³³ bytes (§4 B2, with disclosure).
5. B3 start-up overhead uses a 1-byte input instead of an empty file.
6. B4: not run (§9).

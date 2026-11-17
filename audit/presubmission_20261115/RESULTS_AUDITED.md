# RESULTS_AUDITED — run 20261114_050438_SVGX-2026-11-A

Evidence source: `results/20261114_050438_SVGX-2026-11-A/11_reports/RESULTS_UZ.md`, SHA-256
`ef97bfcf72ef729ccf422108853c44dfa32661ffb11cf2fad40cc70939807b13`. This is the same hash as in the brief, and the
report is unchanged. All numbers below are recomputed from `ledger.sqlite`, opened read-only, by the scripts in
`analysis/`. Nothing in `results/` was modified.

Labels:
- **[CONFIRMED]**: the original value was reproduced independently.
- **[CORRECTED]**: the original value was wrong; the corrected value is shown next to it.
- **[POST-HOC]**: descriptive or sensitivity analysis added after the run. These are not confirmatory.

## 1. Main comparisons, confirmation (1,076 files, 55 provenance families) — [CONFIRMED]

Recomputed totals, W/T/L and gains equal the report exactly: 0 differences over all comparisons of both splits
(`derived/checks_a02.json`).

| Contrast | ΣA | ΣC_G | Gain % | File W/T/L | Family W/T/L | 99.5 % (marginal) | Bonferroni k=3 |
|---|---:|---:|---:|---|---|---|---|
| G vs C\* (=P) | 39,383,136 | 39,284,709 | 0.2499 | 39/1037/0 | 19/36/0 | [0.0929, 0.9924] | [0.0815, 1.1465] |
| G vs U | 39,289,439 | 39,284,709 | 0.0120 | 37/1037/2 | 18/36/1 | [0.0025, 0.0516] | [0.0013, 0.0612] |
| G vs Brotli-11 | 39,828,585 | 39,284,709 | 1.3655 | 39/1037/0 | 19/36/0 | [0.2728, 6.3213] | [0.2214, 7.1992] |
| G vs I (ablation) | 39,397,286 | 39,284,709 | 0.2857 | 39/1037/0 | 19/36/0 | [0.1023, 1.1168] | [0.0856, 1.2827]\* |
| G vs D | 39,389,320 | 39,284,709 | 0.2656 | 39/1037/0 | 19/36/0 | [0.0968, 1.0671] | [0.0848, 1.2415]\* |
| G vs XWRT-l6 | 39,744,103 | 39,284,709 | 1.1559 | 1010/0/66 | 41/0/14 | — | — |
| G vs xz -9e | 39,841,636 | 39,284,709 | 1.3979 | 1057/0/19 | 50/0/5 | — | — |
| G vs 7z PPMd | 41,171,450 | 39,284,709 | 4.5826 | 1011/0/65 | 44/0/11 | — | — |
| G vs zstd-19 | 40,732,175 | 39,284,709 | 3.5536 | 1070/0/6 | 54/0/1 | — | — |
| G vs gzip -9 | 46,627,803 | 39,284,709 | 15.7483 | 1075/0/1 | 55/0/0 | — | — |

\* For secondary contrasts the report labels the k = 3 interval "Bonferroni". It uses the confirmatory family's k,
so it is not a family-wise interval for those contrasts.

Definitions, from the code (`reporting/stats.py`) and reproduced:
- **Estimand.** Ratio of byte totals, `100(ΣA − ΣC)/ΣA`.
- **File W/T/L.** On integer bytes with no tolerance.
- **Family W/T/L.** Sign of the family's net byte saving.
- **Resampling.** Whole provenance families with replacement, one shared draw for all contrasts. PCG64 seed
  20261113, 50,000 draws, linear-quantile percentile intervals.

Pilot (248 files, 34 families):
- G vs Brotli-11: 1.0771 %, 16/232/0 files, 13/21/0 families.
- G vs U: 0.0102 %.
- G vs I: 0.1703 %.

## 2. Completeness — [CORRECTED]

| Item | Original report | Corrected | Reason |
|---|---|---|---|
| pilot_missing_measurements | 496 | **0** missing; 496 = not scheduled by design | `zstd1`, `gzip1` are speed-only (`runner/controller.py:150`), never scheduled for size, but `reporting/build.py:80-87` counted them as missing |
| confirmation_missing_measurements | 2,152 | **0** missing; 2,152 = not scheduled by design | same (2 methods × 1,076 files) |
| Paired size coverage | "exact_paired_coverage ✓" | 248/248 and 1,076/1,076 files have all 7 size methods measured and round-tripped | `derived/a07_completeness.json` |

The frozen `reporting/build.py` is not edited, because it is hash-bound by `state/freeze.json`. The corrected
accounting lives in `analysis/a07_completeness.py` and is covered by regression tests
(`analysis/test_audit_regression.py`, 5 passed).

## 3. Intervals: audit and sensitivity

- **[CONFIRMED]** The independent re-implementation reproduces all 12 interval endpoints to 4 decimals. Each
  Bonferroni tail contains 42 of 50,000 draws.
- **[POST-HOC sensitivity]** Over 20 other seeds, the Bonferroni lower endpoint of G vs Brotli-11 ranges from
  0.2217 to 0.2426 % (SD 0.005). The upper endpoint ranges from 6.95 to 7.42 %. G vs U lower: 0.0012–0.0017 %.
- **[POST-HOC, not valid for inference]** A file-level bootstrap that ignores family clustering gives a narrower
  G vs Brotli-11 interval, [0.194, 4.748] %. Clustering mostly widens the upper tail.
- The wide upper tail (to about 7 %) reflects concentration (§4). Resamples that repeat the top family inflate the
  ratio.

## 4. Concentration of the G vs Brotli-11 saving (confirmation) — [POST-HOC descriptive]

| Measure | Value |
|---|---|
| Families with positive saving | 19 / 55 (36 families tie: every file raw) |
| Share of total saving: top 1 / top 3 / top 5 families | 28.9 % / 67.9 % / 85.4 % |
| Share of total saving: top 1 / 3 / 5 / 10 files | 28.9 % / 65.1 % / 80.5 % / 90.6 % |
| Leave-one-family-out pooled gain | 0.987 % (drop top family) … 2.099 % |
| Leave-top-k-families-out | k=1: 0.987 %; k=3: 0.462 %; k=5: 0.377 % |
| Equal-family mean gain | 2.33 % |
| File median gain (all files / structured files) | 0.0 % / 3.64 % |

| Category | Files | Families | Structured G | Gain vs Brotli-11 | Ceiling |
|---|---:|---:|---:|---:|---:|
| illustrations | 328 | 23 | 16 | 4.290 % | 4.471 % |
| maps | 140 | 18 | 18 | 1.084 % | 1.095 % |
| diagrams | 208 | 9 | 5 | 0.300 % | 0.325 % |
| icons | 400 | 11 | 0 | 0.000 % | 0.004 % |

| Original size | Files | Structured G | Gain |
|---|---:|---:|---:|
| < 4 KiB | 696 | 0 | 0.000 % |
| 4–64 KiB | 275 | 9 | 0.219 % |
| 64 KiB–1 MiB | 77 | 23 | 4.223 % |
| ≥ 1 MiB | 28 | 7 | 1.065 % |

Per-family table: `derived/family_contributions_confirmation.csv`.

## 5. Mechanism decomposition (confirmation) — [POST-HOC descriptive, exact byte totals]

See `METHOD_SPEC.md` §3.
- Grouping identical rule outputs (I → U) saves 107,847 B (0.274 %).
- Pooling weights (U → G) saves 4,730 B (0.012 %).
- G realises 98.0 % of the free-spelling ceiling (1.3937 %). The whole-system gain is therefore limited by the
  geometry/literal split, not by spelling.

## 6. Speed and memory (69 timing files: 30 pilot + 39 confirmation) — [CONFIRMED] + [POST-HOC]

- **What was measured:**
  - cold process per invocation, 1 warm-up and 7 repeats (all 69 files have 7);
  - one thread, sequential;
  - encode = standalone `svgx encode --profile X`, which builds both branches and selects the smaller;
  - decode = restoring the bytes;
  - memory = Windows job object `PeakJobMemoryUsed`.
- **Throughput definitions:**
  - "MiB/s" = pooled throughput `Σ original bytes / (2^20 · Σ per-file median seconds)`;
  - "peak memory" = the maximum over files and repeats.
  - These definitions were reproduced exactly.
- **Repeatability:** the median coefficient of variation over repeats is 4–5 % for svgx and Brotli.

| Paired, same 69 files (pooled time ratio G / other) | Encode | Decode |
|---|---:|---:|
| G / Brotli-11, all | 1.97 | 0.80 |
| G / Brotli-11, raw-branch files (56) | 1.77 | 0.57 |
| G / Brotli-11, structured files (13) | 2.33 | **1.36** |
| G / P, all | 0.98 | **1.11** |
| G / P, structured files | 0.99 | 1.25 |

- **The decode-time advantage over Brotli-11 is a tool artifact, not an algorithmic result.**
  - On raw-branch files, `svgx` decodes the byte-identical Brotli stream with the same library build.
  - It still does so 0.57× faster than `brotli.exe`, so the difference is CLI and I/O overhead.
  - On the files where G's mechanism is active (structured), G decodes 1.36× slower than Brotli-11.
  - G decodes about 11 % slower than P.
- **Break-even.** A pooled break-even of about 180 decodes (`K = Δenc/Δdec`) exists only because of that tool
  artifact. It is not reported as an algorithmic benefit.
- **Memory.**
  - Per-file median peak: svgx ≈ 4.5 MB, Brotli ≈ 5.3 MB.
  - Maximum: svgx 134.0 MB, Brotli 74.0 MB, XWRT 130.6 MB, xz -9e 707.9 MB.
- **Python reference decoder.** Not part of timing. Median 0.07 s per file, maximum 2.84 s (size pass).
- **Sample limit.** This is a 69-file stratified timing sample (category × size bracket, seeded); only 13 of its
  files are structured.

## 7. XWRT — [POST-HOC descriptive]

- XWRT 3.4 (5.11.2007), commit f2d037a. `-l6` = LZMA with an 8 MB dictionary; confirmed from the tool's own help
  text on 2026-11-15.
- XWRT-l6 is 0.212 % smaller than Brotli-11 in total, yet larger on 996/1,076 files (W/T/L 80/0/996). It loses on
  small files and wins on a few large ones.
- G vs XWRT-l6 is therefore a comparison of complete systems with different back ends (Brotli vs LZMA). It does not
  compare transforms.

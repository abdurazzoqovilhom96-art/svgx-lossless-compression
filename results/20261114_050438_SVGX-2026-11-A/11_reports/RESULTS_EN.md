# Results

Run: `20261114_050438_SVGX-2026-11-A`  ·  Scope: full  ·  Generated: 2026-11-14T06:25:14Z

## Dated pilot decision record
- Selected practical control C*: **P** (D=21558138, P=21554212 bytes; smaller pilot aggregate of D/P; ties -> P)
- Pilot summary hash: `18a02719c77c53ade0efcf24d0664e5be6f5a2f1898454fee056e3ba13619cdd`
- Recorded (UTC): 2026-11-14T05:30:54Z

## pilot (248 files)

| Comparison | Files | ΣA | ΣC | Gain % | File W/T/L | Family W/T/L | 99.5% interval | Bonferroni |
|---|---|---|---|---|---|---|---|---|
| G_vs_Cstar | 248 | 21554212 | 21525110 | 0.1350 | 16/232/0 | 13/21/0 | — | — |
| G_vs_U | 248 | 21527314 | 21525110 | 0.0102 | 16/232/0 | 13/21/0 | — | — |
| G_vs_brotli11 | 248 | 21759491 | 21525110 | 1.0771 | 16/232/0 | 13/21/0 | — | — |
| G_vs_I | 248 | 21561829 | 21525110 | 0.1703 | 16/232/0 | 13/21/0 | — | — |
| G_vs_D | 248 | 21558138 | 21525110 | 0.1532 | 16/232/0 | 13/21/0 | — | — |
| G_vs_P | 248 | 21554212 | 21525110 | 0.1350 | 16/232/0 | 13/21/0 | — | — |
| G_vs_xwrt_l6 | 248 | 22368294 | 21525110 | 3.7695 | 239/0/9 | 28/0/6 | — | — |
| G_vs_xz9e | 248 | 21932480 | 21525110 | 1.8574 | 241/0/7 | 33/0/1 | — | — |
| G_vs_ppmd7z | 248 | 22268115 | 21525110 | 3.3366 | 244/0/4 | 30/0/4 | — | — |
| G_vs_zstd19 | 248 | 22039845 | 21525110 | 2.3355 | 248/0/0 | 34/0/0 | — | — |
| G_vs_gzip9 | 248 | 23464198 | 21525110 | 8.2640 | 248/0/0 | 34/0/0 | — | — |

- Style-free optimistic ceiling vs raw Brotli: 1.0939%
- 1% size target: met (1.0771%)
- Two-thirds family breadth target: missed (13/34)
- G: structured files 16, raw fallback 232; forced-structured gross gain/loss: 234381/36587 bytes
- Tokens: 316352; multi-rule matches (collisions): 309554; escapes (G): 79

## confirmation (1076 files)

| Comparison | Files | ΣA | ΣC | Gain % | File W/T/L | Family W/T/L | 99.5% interval | Bonferroni |
|---|---|---|---|---|---|---|---|---|
| G_vs_Cstar | 1076 | 39383136 | 39284709 | 0.2499 | 39/1037/0 | 19/36/0 | [0.0929, 0.9924] | [0.0815, 1.1465] |
| G_vs_U | 1076 | 39289439 | 39284709 | 0.0120 | 37/1037/2 | 18/36/1 | [0.0025, 0.0516] | [0.0013, 0.0612] |
| G_vs_brotli11 | 1076 | 39828585 | 39284709 | 1.3655 | 39/1037/0 | 19/36/0 | [0.2728, 6.3213] | [0.2214, 7.1992] |
| G_vs_I | 1076 | 39397286 | 39284709 | 0.2857 | 39/1037/0 | 19/36/0 | [0.1023, 1.1168] | [0.0856, 1.2827] |
| G_vs_D | 1076 | 39389320 | 39284709 | 0.2656 | 39/1037/0 | 19/36/0 | [0.0968, 1.0671] | [0.0848, 1.2415] |
| G_vs_P | 1076 | 39383136 | 39284709 | 0.2499 | 39/1037/0 | 19/36/0 | [0.0929, 0.9924] | [0.0815, 1.1465] |
| G_vs_xwrt_l6 | 1076 | 39744103 | 39284709 | 1.1559 | 1010/0/66 | 41/0/14 | — | — |
| G_vs_xz9e | 1076 | 39841636 | 39284709 | 1.3979 | 1057/0/19 | 50/0/5 | — | — |
| G_vs_ppmd7z | 1076 | 41171450 | 39284709 | 4.5826 | 1011/0/65 | 44/0/11 | — | — |
| G_vs_zstd19 | 1076 | 40732175 | 39284709 | 3.5536 | 1070/0/6 | 54/0/1 | — | — |
| G_vs_gzip9 | 1076 | 46627803 | 39284709 | 15.7483 | 1075/0/1 | 55/0/0 | — | — |

- Style-free optimistic ceiling vs raw Brotli: 1.3937%
- 1% size target: met (1.3655%)
- Two-thirds family breadth target: missed (19/55)
- G: structured files 39, raw fallback 1037; forced-structured gross gain/loss: 543876/1259778 bytes
- Tokens: 2706496; multi-rule matches (collisions): 2610128; escapes (G): 2378

### Claim criteria
- exact_paired_coverage: ✓
- adjusted_lower_endpoints_positive: ✓
- G_total_below_remaining_control: ✓
- raw_brotli_gain_at_least_1_percent: ✓
- strict_family_wins_two_thirds: ✗
- G_vs_I_positive: ✓
- broad_success_claim: ✗
- lower_bound_exceeds_1_percent: ✗
- Broad success claim: ✗

## Time and memory (cold process, per-file medians)

| Method | Files | Encode MiB/s | Decode MiB/s | Peak memory (bytes) |
|---|---|---|---|---|
| brotli11 | 69 | 0.83 | 30.29 | 73973760 |
| gzip1 | 69 | 7.68 | 8.13 | 7131136 |
| gzip9 | 69 | 6.06 | 8.13 | 7184384 |
| ppmd7z | 69 | 7.29 | 6.95 | 137879552 |
| svgx_D | 69 | 0.41 | 47.16 | 133976064 |
| svgx_G | 69 | 0.42 | 37.63 | 133955584 |
| svgx_I | 69 | 0.42 | 36.23 | 133992448 |
| svgx_P | 69 | 0.42 | 41.73 | 133967872 |
| svgx_U | 69 | 0.42 | 37.95 | 133963776 |
| xwrt_l6 | 69 | 2.56 | 5.41 | 130629632 |
| xz9e | 69 | 3.99 | 23.91 | 707878912 |
| zstd1 | 69 | 54.20 | 30.26 | 6139904 |
| zstd19 | 69 | 4.47 | 30.75 | 97087488 |

## Completeness audit
- job_status_counts: {'done': 16444}
- failed_attempts: 0
- events: 1
- pilot_files_verified: 248/248
- confirmation_files_verified: 1076/1076
- pilot_missing_measurements: 496
- confirmation_missing_measurements: 2152

Regenerate: `python study.py report --run-id 20261114_050438_SVGX-2026-11-A`

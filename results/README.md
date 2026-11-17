# Results of run `20261114_050438_SVGX-2026-11-A`

This is the only completed SVGX run. It uses design `SVGX-2026-11-A`, which was frozen on 2026-11-13T17:38:03Z with the SHA-256 digests of 53 bound files (see `../state/freeze.json`), and a single build, `build-fb5b391323df`.

- **Pilot** files (248 files, 34 families) were measured first. They were used only to select the control C\* by a rule fixed in advance (P was selected: 21,554,212 B against 21,558,138 B for D) and to evaluate the pilot targets. The decision is recorded in `07_statistics/pilot_decision.json`, written 2026-11-14T05:30:54Z, before any confirmation job.
- **Confirmation** files (1,076 files, 55 families, no family shared with the pilot) are the **final** results.

## Contents

| Folder / file | Content |
|---|---|
| `ledger.sqlite` | Every measurement job (16,444), with its full JSON result. This includes per-variant sizes, section lengths, codec statistics, the verification of both decoders, and the comparator sizes and round trips. Open it read-only. SHA-256 `514a47d8…a99a` |
| `01_protocol/` | Freeze, approval, environment (no host or user identifiers), comparator definitions, run metadata |
| `02_corpus/` | Manifests used by the run (`pilot.csv`, `confirmation.csv`, `dedup.csv`, `sources.csv`, `design.json`) |
| `03_raw/*_per_file.csv` | Per-file sizes of every variant and comparator. The compressed streams (933 MB) are not included; they can be regenerated with the codec |
| `04_verification/` | Per-file reconstruction checks (native and reference decoder, final and forced streams) |
| `05_ablations/` | Per-file sizes of the five spelling variants D, P, I, U, G and the free-spelling bound |
| `06_performance/` | `timing_repeats.csv` (every timed repeat: 69 files × 13 methods × 8, including the warm-up) and `timing_summary.json` |
| `07_statistics/` | Family-cluster bootstrap results (50,000 resamples, PCG64 seed 20261113) and the pilot decision |
| `08_plot_data/`, `09_figures/` | Data and figures produced by the run's own report builder |
| `10_tables/` | Main comparison tables for the pilot and the confirmation split |
| `11_reports/` | Run reports (English and Uzbek), completeness audit, failure/retry log (0 failed attempts) |
| `12_reproducibility/` | Archive manifest and package verification |

## Diagnostic analyses

Post hoc diagnostic analyses are in `../audit/presubmission_20261115/`. They comprise:
- an independent recomputation of all tables (0 differences);
- a completeness correction;
- concentration, leave-one-family-out and seed-sensitivity analyses;
- the re-hashing of 14,564 stored streams;
- the re-decoding of the 39 structured confirmation streams with the reference decoder (39/39 restored).

`../analysis/summarize_results.py` regenerates every value quoted in the top-level README from `ledger.sqlite` and checks it against `10_tables/`.

## Known issues

1. **Spurious "missing measurements".** `11_reports/RESULTS_*.md` and `completeness_audit.json` report 496 (pilot) and 2,152 (confirmation) "missing measurements". These are the speed-only methods `zstd1` and `gzip1`, which were never scheduled for size, so the count is a counter error in `reporting/build.py`. All seven size methods were measured for every file (`../audit/presubmission_20261115/RESULTS_AUDITED.md` §2).
2. **Licences.** 37 confirmation files lie outside the study's open-licence allow-list (`../data/FILES_OUTSIDE_ALLOWLIST.csv`). All 37 used the raw branch; excluding them changes the final gain from 1.3655 % to 1.3673 %.
3. **Decode speed.** The decode throughput of `svgx` in `06_performance/` exceeds that of the `brotli` tool even on files where both decode the identical Brotli stream. This is command-line overhead, not an algorithmic advantage; on structured files G decodes 1.36× slower than Brotli-11.

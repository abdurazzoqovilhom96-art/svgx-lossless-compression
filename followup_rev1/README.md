# SVGX-REV1: follow-up experiments

This folder holds the follow-up design **SVGX-REV1** of the SVGX study (base design SVGX-2026-11-A, run
`20261114_050438_SVGX-2026-11-A`). It answers three questions that the first study left open:

1. **B1. Ablation.** How much of the saving requires geometric prediction, as opposed to separating the coordinates
   from the text or re-coding them as integers?
2. **B2. Strong comparators.** Does geometric modelling still help when the back end is a context-mixing compressor
   (paq8px v217)? The comparison also covers Zstandard with a dictionary and Brotli with other window settings.
3. **B3. Speed.** How fast are encoding and decoding in process, without command-line start-up costs?

All results are a **pre-specified re-analysis of previously analysed data**. The design uses the same frozen
confirmation split (1,076 files, 55 provenance families) as the first study. Nothing was tuned on it; all
calibration used the pilot split.

## Protocol, freeze and approval

- **Protocol:** `docs/PROTOCOL_REV1.md`, written before any measurement on the confirmation split.
- **Freeze record:** `state/freeze_rev1.json` (SHA-256 `4a300051…0c`), created on 2026-11-16 at 07:25:56 UTC. It holds the SHA-256 digests of
  the 57 files that define the experiment (all included here) and of the tools.
- **Approval record:** `state/approval_rev1.json`, written at 07:43:42 UTC. It is bound to the digest of the freeze
  record. Every experiment script refuses to touch the confirmation split without a matching approval.
- **Regression gate R0.** Before any other measurement, the extended build reproduced the first study byte for byte
  on all 1,076 confirmation files. This covers the raw stream, the final and forced streams of all five variants, and
  the statistics records.

## Contents

| Path | Content |
|---|---|
| `rev1/` | Experiment scripts: R0, B1, B2, B3, power simulation, freeze, approval, analysis |
| `tests_rev1/` | Tests of the follow-up code (15) |
| `codec/` | Rust sources of the extended codec. It adds two options, `--modes` (restricted mode sets) and `bench` (in-memory timing), and leaves the format, the decoders and the default behaviour unchanged. The Brotli C sources (`codec/third_party/brotli`) are the same as in the first study's run package and are not repeated here. |
| `config/` | Frozen parameters (`rev1.toml`), paq8px calibration, Zstandard pilot dictionary, CPU topology, timing sample, licence-sensitivity list, power simulation |
| `data/manifests/` | Pilot and confirmation manifests (unchanged from the first study) |
| `reference/decode.py`, `runner/measure.py`, `baselines/adapters.py` | Unchanged files of the first study that the follow-up imports (part of the freeze) |
| `state/` | Freeze record, approval record and the pre-freeze test log |
| `results_rev1/` | Per-file records of R0, B1, B2 and B3, the run log and the analysis (`analysis/confirmation/estimands.json`, per-file CSVs) |
| `READY_REV1_UZ.md` | Readiness report written before the approval (in Uzbek; part of the freeze) |
| `run_rev1.cmd` | Runs R0 → B1 → B3 → B2 → analysis on Windows |

### Tools not included

| Tool | Version | SHA-256 recorded in the freeze |
|---|---|---|
| paq8px | v217, `paq8px_v217_windows_x64.7z` from https://github.com/hxim/paq8px/releases | archive `f5be98bf…62f1c`, binary `4e530a62…5ed4` |
| Zstandard | 1.5.7 (official Windows build) | `8076aae0…4111` |
| Brotli command-line tool | 1.2.1, built from source as in the first study | `c34ccd06…d8b1` |

## Results (confirmation split)

Intervals are Bonferroni-adjusted family-cluster bootstrap percentile intervals. They use 50,000 resamples (seed
20261116) and give 99.5% family-wise coverage for the three confirmatory estimands.

| Estimand | Estimate | Interval | Pre-specified wording |
|---|---|---|---|
| R1: share of the saving lost when only mode 00 is allowed | 0.772 | [0.446, 0.981] | prediction contributes a substantial share |
| Gain_H: hybrid (paq8px literal stream + geometric sections) vs paq8px | 0.184% | [0.000, 1.646]% | no material gain over a strong back end |
| τ_dec: G vs Brotli decoding time, structured files | 7.078 | [4.063, 14.425] | slower by 7.08× |

Secondary results:

- **Ablation.** Mode 11 alone supplies about half of the saving: R11 = 0.517.
- **Coding without prediction.** Coding the coordinates without prediction (Z) never beat Brotli.
- **Separation only.** T beat Brotli on one file only.
- **paq8px versus Brotli.** paq8px was 18.5% smaller than Brotli-11.
- **SVGX versus paq8px.** SVGX output was 21.1% larger than paq8px.
- **Zstandard.** SVGX was 6.25% smaller than Zstandard with the pilot dictionary.
- **Brotli default window.** Against Brotli with the command-line default window, the gain was 0.52%, and its interval includes zero.
- **Encoding time.** Encoding took 1.92 times as long as Brotli.

`results_rev1/analysis/confirmation/estimands.json` holds every estimate with its percentile, Bonferroni and BCa
intervals.

## Re-running

1. Unpack the first study's run package and the complete ledger.
2. Place this folder's files over a copy of that project.
3. Install the tools listed above. Their paths, and the path of the first study's project, are set in
   `rev1/common.py`; adjust them for another machine.
4. Follow `docs/PROTOCOL_REV1.md`: the preparation gates on fixtures and pilot (R0, the T/Z self-check, the B1, B2
   and B3 pilot runs, calibration, tests), then `rev1/freeze.py` and `rev1/approve.py`, then `run_rev1.cmd`.

`rev1/freeze.py` refuses to write a freeze record unless every preparation gate has passed. A new freeze record has a
new digest, so a re-run needs its own approval. The original run took 75 s (R0), 332 s
(B1), 6,666 s (B3) and 12,480 s (B2) on an Intel Core i5-13400F.

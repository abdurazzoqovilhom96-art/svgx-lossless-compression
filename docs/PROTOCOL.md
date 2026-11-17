# Study protocol — design SVGX-2026-11-A (registered before approval)

## 1. Question
Given the decoded exact source-coordinate value, its grammatical role and the previously decoded
tokens, does grouping formatting rules that emit identical source bytes (arm **G**) reduce complete
SVG file size compared with a matched rule-identifier coder (**I**), a grouped max-weight coder
(**U**), explicit descriptors (**D**), a previous-descriptor predictor (**P**) and general-purpose
compression? Full encode time, decode time and memory are measured as well.

## 2. Materials
- Codec `svgx` (Rust, `codec/`), wire format `docs/FORMAT.md`, independent Python decoder
  `reference/decode.py`. All five arms share one container, one parse and identical literal,
  schedule and geometry bytes per file (verified by section hashes).
- Comparators (`config/baselines.toml`): Brotli 1.2.1 q11 w22 (primary, `brotli.exe` built from the
  same pinned source as the codec), XWRT 3.4 `-l6`, xz 5.8.4 `-9e`, 7-Zip 26.05 PPMd `-mx=9`,
  zstd 1.5.7 `-19`, GNU gzip 1.15 `-9 -n`; speed references zstd `-1`, gzip `-1`. Each is decoded with
  its own tool. SVG optimisers are excluded (different fidelity endpoint).

## 3. Corpus and splits (frozen before any compression)
- Categories: maps, illustrations, diagrams, icons. Targets: pilot 100 and confirmation 400 per
  category (new design choice). If infeasible, the actual counts are frozen as a labelled reduced
  design (`data/manifests/design.json`); repeated copies are never used.
- Sources: npm icon packages, GitHub emoji sets (pinned commits), Wikimedia Commons (per-file
  revision timestamp + SHA-1, free licences only), plus @svg-maps. Every file: URL, revision, raw
  SHA-256, size, category, creator family, licence, source (`data/manifests/*.csv`).
- Exact duplicates removed; near-duplicates/provenance relatives grouped by union-find over creator
  family, declared lineage (forks/derivatives), normalized-content hash, shared path data
  (Jaccard ≥ 0.5) and Commons title stems. The component is the **statistical provenance family**
  and lies wholly in one split across all categories. Decisions: `data/manifests/dedup.csv`.
- Per family, per category, per split at most 25 % of the category quota (so at least four families
  are needed to fill a category). Components are assigned to the split with the lower fill ratio
  (capacity / quota) over their categories; recency breaks ties. Selection: seeded
  round-robin over families (seed `SVGX-2026-11-A/selection/v1`), random within family (retains the
  observed size distribution below the 25 MB admission limit). Confirmation prefers components whose
  works date from 2025-07-01 or later. Historical manifests are unavailable, so historical overlap is
  unverifiable; this limitation is reported.
- Timing sample: per split, every category × size bracket (0, 4 KiB, 64 KiB, 1 MiB) with files, three
  files per cell by seeded hash of metadata only (`data/manifests/timing_*.csv`).

## 4. Measurements
- Size pass (parallel, bounded workers): `svgx encode-all` (all arms, shared geometry), independent
  `brotli.exe` stream, every comparator compress + own decompress. Every project stream (final and
  forced) is decoded by the native decoder and by the Python reference decoder in separate processes;
  bytes compared with the original; SHA-256 recorded.
- Invariants per file and arm: `C ≤ B`; raw fallback byte-equal to the independent baseline;
  structured branch only when strictly smaller; `O ≤ C`; header + sections reconcile exactly; common
  sections identical across arms; escape section identical across I/U/G.
- Timing (sequential, no background jobs): cold process per invocation, one warm-up, seven measured
  repeats per method × file, reproducibly interleaved; threads limited to one; standalone
  `svgx encode --profile X` recomputes geometry and the Brotli branch; decode to restored bytes.
  Memory: Windows job object `PeakJobMemoryUsed` (bytes). Per-file median; pooled throughput
  `Σ bytes / (2^20 · Σ median seconds)`. Post-decode verification and the Python reference pass are
  tracked separately.

## 5. Statistics
`Gain(A, G) = 100 (ΣA − ΣC_G) / ΣA` on identical files (ΣA > 0). Family net `g_j = Σ(A_i − C_i)`:
win/tie/loss for `>0/=0/<0`, ties in the denominator. Reported: pooled gain, file-level median relative
gain, class totals, equal-family mean, strict file wins, leave-one-family-out range, family dominance,
optimistic style-free ceiling `100 (ΣA − ΣO)/ΣA`, forced-structured gross gains/losses, style counts,
escapes and collisions.

**Prespecified confirmatory contrasts:** (1) G vs C\*, C\* = the smaller pilot aggregate of D and P
(ties → P), recorded in a dated decision record with the pilot summary hash after the pilot and
before confirmation; (2) G vs U; (3) G vs raw Brotli-11. Also G vs I (mechanistic ablation), G vs D,
G vs P and G vs each available comparator by name.

**Confirmation intervals:** 50 000 paired resamples of whole families (numpy `PCG64`, seed 20261113,
`linear` quantiles), identical draws for every contrast; marginal 99.5 % (0.0025, 0.9975) and
Bonferroni (0.005/6, 1 − 0.005/6). Fewer than two families or an undefined denominator → finite-corpus
figures only, interval unavailable.

**Pilot assessment (no tuning after observing sizes):** size target `100(ΣB − ΣC_G) ≥ ΣB`; breadth target
`3 · wins ≥ 2 · m` (family strict wins vs raw Brotli). Full-scope approval proceeds to confirmation for
every valid pilot outcome, including a large loss.

**Broad success claim:** exact paired coverage; all three Bonferroni lower endpoints > 0; G total below
the remaining D/P control; `100(ΣB − ΣC) ≥ ΣB`; `3 · wins ≥ 2 · m` over confirmation families; positive
G-vs-I gain. A lower bound above 1 % is a separate claim. Generalisation is limited to the measured
object classes and provenance.

## 6. Authorization, failures and resumption
- Preparation is pre-authorized; real runs require a recorded decision (`state/approval.json`) bound to
  the SHA-256 of `state/freeze.json`, checked at every entry point and before every job launch (also on
  resume). Missing, declined, empty or hash-mismatched decisions yield zero launches. Pilot-only
  approval dispatches only pilot jobs.
- Ledger: SQLite (WAL, `BEGIN IMMEDIATE` transactions), idempotent key
  `split|input_sha256|build_id|method|repeat|task`, per-run lock, retries for transient failures.
- A deterministic round-trip mismatch, formula violation or mismatched primary baseline is a defect:
  evidence is kept (`04_verification/defects/`), the affected comparisons are paused, the build's
  affected results are invalid. A fix that restores this specification registers a linked build with
  the same design ID and new hashes, passes synthetic readiness again and remeasures all affected
  paired comparisons. Material changes of scope, protocol or split require a new question.

## 7. Implementation decisions (recorded)
| ID | Decision |
|---|---|
| D-01 | Pins: newest release at least two weeks old on 2026-11-13; SHA-256 verified on every acquisition; Python packages uploaded before 2026-10-30 (`pip --uploaded-prior-to`), lock by pip-tools with hashes. |
| D-02 | Brotli: Google C 1.2.1 compiled with identical flags (`-O2 -fno-fast-math -ffp-contract=off -fno-strict-aliasing`) into the codec and `brotli.exe`; quality 11, lgwin 22 fixed for every file (the CLI's automatic small-file window is not used), size hint = input length as in the CLI. |
| D-03 | Toolchain without administrator rights inside `.tools/`: Rust 1.99.0 `x86_64-pc-windows-gnu`, WinLibs GCC 16.2.0 (MinGW-w64 14, msvcrt) as C compiler and linker; the codec has no third-party crates. |
| D-04 | Header: fixed 60 bytes little-endian; profile byte D=1, P=2, I=3, U=4, G=5. |
| D-05 | Literals and schedule are Brotli-11 streams; schedule = canonical LEB128 fields. |
| D-06 | Bounded exact arithmetic `|x| < 2^126` for every predictor intermediate and residual (`z < 2^127`); a violating predictor is unavailable (never selected; rejected by decoders). |
| D-07 | XWRT 3.4 (commit f2d037a) built from the upstream Makefile's Windows file list with g++ `-std=gnu++98`; level `-l6` = LZMA 8 MB per its help text. |
| D-08 | P: the previous descriptor of the role is rendered exactly with the fallback rule (sign compatibility included). The first event of a role and an inapplicable previous descriptor are implicit escapes (no symbol); otherwise a match/escape symbol is coded with an adaptive binary model on the shared arithmetic coder (same update/rescale rule). |
| D-09 | I codes the highest-weight matching rule (ties smallest ID); decoders reject other choices and escapes when a rule matches. |
| D-10 | Mode-11 search ranks candidates by IEEE double SSD of affine coordinates, ties by distance, evaluates the first eight usable ones exactly; encoding is single-threaded per file. |
| D-11 | Grid K over geometry-relevant tokens only: every endpoint coordinate plus the control tokens of modeled blocks. Arc radii/flags, S/Q controls and remainder controls do not influence K. |
| D-12 | Wikimedia bans bursts from unidentified generic clients (observed 2026-11-13: `429` with `Retry-After: 600` after a few downloads at 0.6–2.5 s spacing). A generic User-Agent is kept (no personal contact data), and Commons is fetched in *trickle mode*: round-robin over categories/seeds, ≤ 6 files per page visit, 20 s between downloads, per-run time budget, stop (resumable) on any ban longer than 120 s. Candidate pool targets 750/750/450 (maps/diagrams/illustrations) are upper bounds; the frozen design records the counts actually acquired. Additional permissively licensed sources compensate (GitHub: Vega-Lite, matplotlib and ggplot2 test baselines, D2 e2e diagrams, mledoze/countries maps, Firefox emoji, game-icons; npm: @svg-maps, maki). |
| D-13 | At most 160 candidates per npm/GitHub source by seeded hash order before selection; files over 25 MB not admitted. The per-family cap was first set to 10 % and changed to 25 % before the freeze, using candidate metadata only (no compression), because the Commons rate limit left few independent families in maps, diagrams and illustrations; split assignment balances fill ratios so that each category has families in both splits. |
| D-14 | Path grammar is SVG 1.1 BNF, including the comma-wsp before the first arc flag; files without the SVG namespace (also when only an external DTD would supply it) are not modeled; encoding allowlist as in FORMAT §13. |
| D-15 | Timing in cold processes for all methods; per-file median of seven repeats after one warm-up. |
| D-16 | Packages exclude regenerable stream files and the originals; manifests carry URL, revision and SHA-256 for re-fetching under each source's terms. |
| D-17 | Exit codes: 0 ok, 2 not prepared/usage, 3 approval pending, 4 refused/declined/hash mismatch, 5 paused by a defect. |

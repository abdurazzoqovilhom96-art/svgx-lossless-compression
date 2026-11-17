# Prior work, attribution and search log

## Attribution

This study restarts the user's byte-exact geometric SVG project. Its first archive proposed
**I1** (exact numeric value plus exact lexical form), **I3** (generator style and exceptions) and
**OP-07/08** (charged costs and interaction with a subsequent compressor). The present design keeps
those ideas: the decoder reconstructs the exact value before its spelling (I1), spelling styles are a
frozen rule family with an escape (I3), and every byte of every section is charged and compared with
general-purpose compressors on whole files (OP-07/08). Historical numbers from earlier pilots are
motivation only (master specification §"Question and evidence"); no result of this project relies on
them, and no novelty is claimed from an old archive or a favourable dataset.

Established building blocks used without novelty claim: separating XML structure from data (XMill),
shared geometry/prediction, exact lexical-form preservation (EXI fidelity options), arithmetic coding
with adaptive frequency counts, and probability aggregation over models.

## Search log (2026-11-13, web search; queries verbatim)

| # | Query | Closest results | Fidelity definition found |
|---|---|---|---|
| 1 | `lossless SVG path data compression byte-exact numeric formatting` | svgcmp (bytecode, fixed-point + varint, "faithful reconstruction for the tested static subset"); silk (SVG optimiser; precision 0 keeps numbers exact, deterministic); US 8930924 (layered path encoding, lossless when all reconstruction sets are kept); svg-path-simplify; svg_path formatter options | Visual or numeric equivalence; none guarantees the original byte string of `d` |
| 2 | `EXI efficient XML interchange lexical values preserve fidelity option` | W3C EXI Best Practices, EXI primer drafts, EXI C14N (2018) | `Preserve.lexicalValues`: lexical form of element/attribute values is preserved when the option is set; off by default |
| 3 | `lossless compression floating point text CSV decimal formatting reproduce exact string` | DeXOR (arXiv 2603.06581, decimal-space float streams); float-to-string literature | Value-lossless for binary floats; original text spelling not addressed |
| 4 | `NYX byte-exact genomic text compression decimal rewrite preprint` (+ the master link PMC13648360) | Patsakis et al., *Byte-exact, format-aware compression for FASTA, FASTQ, BED and VCF files*, bioRxiv 2026 (doi 10.64898/2026.03.16.712193); Genozip; Hecate | "Byte exact by construction": reversible format transforms, per-block re-decode check with verbatim fallback; fixed-point decimals split into sign, integer part, fraction length and fraction value; non-canonical integers go to an exception stream |
| 5 | `Calemme elastic lossless contour coding depth video APSIPA transactions` | Calemme, Cagnazzo, Pesquet-Popescu, APSIPA TSIP 2014/15, doi 10.1017/ATSIP.2014.20 | Lossless contour coding with an elastically deformed reference contour as side information (geometry prediction from a reference shape) |
| 6 | `genozip VCF lossless numeric field compression preserving original text formatting` | Genozip (Bioinformatics 2020), GSC (GigaScience 2024) | Lossless VCF compression (MD5 verification); handling of numeric spellings not documented in the results |
| 7 | `probability aggregation multiple predictors produce same symbol mixture context model compression "same output" equivalent predictions` | PAQ / context mixing (linear, logistic, geometric weighting; Mattern 2013) | Mixing of model distributions; no source discusses grouping *rules whose outputs coincide* |

Reference starting points from the master specification: XMill (Liefke & Suciu, SIGMOD 2000,
doi 10.1145/335191.335405) — XML structure/data separation and per-container compression; W3C EXI
§6.3 fidelity options; Calemme et al.; the bioRxiv byte-exact genomic preprint above.

## Closest implementations and how the claim is narrowed

1. **Byte-exact genomic text compression (bioRxiv 2026).** Closest fidelity definition (byte-exact,
   verified, verbatim fallback ≈ our raw-Brotli branch and C ≤ B invariant) and closest numeric idea
   (decimals split into sign/integer/fraction length/fraction value ≈ our descriptor). Our arm **D** is
   the fair analogue of that explicit-descriptor approach and arm **P** of a previous-style predictor;
   both are compared directly. Difference under test: spelling is predicted *after* the exact value is
   decoded, by a fixed rule family whose rules emitting identical bytes are grouped (G) with summed
   weights.
2. **EXI with `Preserve.lexicalValues`.** Preserves lexical forms but transmits them as strings; no
   value-conditioned spelling model. Not run as a comparator (different container and fidelity
   scope); recorded as a limitation.
3. **SVG optimisers / bytecode formats (silk, svgcmp, SVGO-like tools).** Different fidelity endpoint
   (rendering or numeric equality), so excluded from size comparisons (master §5).
4. **Context mixing (PAQ family).** Aggregates model probabilities but does not merge *output-
   equivalent rule identities*; the matched ablations I (rule IDs) and U (grouped, max weight) isolate
   exactly that difference. Because U already removes synonymous names, **G vs U** is the direct test
   of whether pooling weights adds value; **G vs I** is the mechanistic ablation (FORMAT §9, PROOF §3).

No identical prior implementation of a value-conditioned, output-grouped spelling model for exact SVG
path data was found in this search. This is a search result on the stated queries and date, not a
proof of absence; any later-found identical work will be acknowledged and the claim narrowed to the
demonstrable difference.

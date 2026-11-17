# Worked example: the geometric model on one corpus file

Figs. 2 and 6 and the path-data strip of Fig. 1 show the model on one file of the confirmation split instead of
synthetic coordinates. Only this file was processed, for visualization; no size or time was measured.

**Selection rule** (`select_example.py`): among the confirmation files whose G output used the structured stream and
whose licence is public domain, CC0 or CC BY, the one with the most modelled blocks. Result: `C-map-6e99fcb1eefa`,
Wikimedia Commons *File:Sibiu County 1937.svg*, public domain, 3,438,750 bytes, SHA-256
`6e99fcb1eefa7f8bd1f21940a2164871dfd113579da454956020bdc184592477`, 6,580 blocks; G is 16.8 % smaller than Brotli-11.

**Export** (`export_handles.py`): the file is encoded with `svgx encode --profile G` (683,976 bytes, equal to `C_G` of
the run) and decoded by a temporary copy of `reference/decode.py` with two logging statements added. The decoded file
is byte-identical to the original. The output, `analysis/output/figure_data/example_file_handles.csv`, has one row per
segment: block index, grid exponent `K`, mode, backward distance of mode 11 (`ref_dist`), the junctions `j0`, `j1`, the
predicted handles `ph0`, `ph1` and the decoded handles `h0`, `h1` (integers on the path's grid; divide by 10^K for SVG
user units).

**What the figures show.** Of the 6,580 blocks, 7 use mode 00, 1,556 mode 01, 1,058 mode 10 and 3,959 mode 11. Mode 11
covers mostly the lettering and the settlement symbols, which the file stores as repeated outlines; modes 01 and 10 the
rivers and borders. 41.0 % of the 105,280 control coordinates are predicted exactly, and the residual is smaller in
absolute value than the handle component in 85.9 % of the cases. Fig. 2 uses blocks 1631 (mode 01, a river) and 6304
(mode 11, a settlement symbol copied from block 6194; all 16 residuals are zero).

The original SVG file is not redistributed; it can be fetched from its source (see `data/manifests/confirmation.csv`)
and checked against the SHA-256 above.

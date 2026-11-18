# Figures of the submitted manuscript

This folder holds the five figures of the submitted article as vector PDFs (`final/`), their editable sources and the scripts that generate them from the saved measurements. The earlier matplotlib versions in `../output/figures/` are drawn from the same data; they are kept for reference.

| Figure | Content | Data | Generator | Source |
|---|---|---|---|---|
| Fig. 1 | Encoder schematic; path strip copied verbatim from the example file | `../output/figure_data/example_file_handles.csv`, the example file | drawn by hand in draw.io | `final/Fig1.pdf` |
| Fig. 2 | Modes 01 and 11 on two blocks of the example file (blocks 1631 and 6304) | `../output/figure_data/example_file_handles.csv` | `scripts/fig2_drawio.py` | `drawio/Fig2.drawio` |
| Fig. 3 | Per-file saving against file size, 1,076 confirmation files | `../output/figure_data/fig3_file_gain_vs_size_confirmation.csv` | `scripts/fig3_drawio.py` | `drawio/Fig3.drawio` |
| Fig. 4 | Concentration of the saving; saving by category | `../output/figure_data/fig4_*.csv`, `fig5_decomposition_confirmation.csv` | `scripts/fig4_drawio.py` | `drawio/Fig4.drawio` |
| Fig. 5 | The example file: real rendering, decoded geometry, magnitudes of coded values | `../output/figure_data/example_file_handles.csv`, the example file | `scripts/render_example_views.ps1`, `scripts/fig5_example.py` | `final/Fig5.pdf` |

## Reproducing

All scripts take their input paths as arguments and recompute every number they print; they stop with an assertion error if a number differs from the one reported in the article (for example the bracket statistics of Fig. 3 against Table 5, or the 41.0 % and 85.9 % of Fig. 5).

```
python -I scripts/fig2_drawio.py  ../output/figure_data/example_file_handles.csv  Fig2.xml
python -I scripts/fig3_drawio.py  ../output/figure_data/fig3_file_gain_vs_size_confirmation.csv  Fig3.xml
python -I scripts/fig4_drawio.py  ../output/figure_data  Fig4.xml
```

The XML files open in draw.io (Extras, Edit Diagram) and export to PDF. The plots inside them are exact SVG images embedded as data; cards, labels and boxes are ordinary draw.io shapes.

Fig. 5 needs the original SVG, which this repository does not redistribute. Download *File:Sibiu County 1937.svg* from Wikimedia Commons (public domain) and check its SHA-256 digest, `6e99fcb1eefa7f8bd1f21940a2164871dfd113579da454956020bdc184592477`. Then:

```
powershell -File scripts/render_example_views.ps1 -Svg <the downloaded file> -OutDir renders
python -I scripts/fig5_example.py ../output/figure_data/example_file_handles.csv <the downloaded file> renders/full.png renders/zoom.png Fig5.pdf
python -I scripts/check_modes_by_element.py <the downloaded file> ../output/figure_data/example_file_handles.csv
```

`render_example_views.ps1` renders the file with headless Microsoft Edge (Chromium); the two PNG files used for the published figure are in `renders/`. Panel (a) is the complete file, panel (b) the window x 1130–1290, y 1440–1560 in SVG user units. Decoded junctions, handles and control points are drawn over the rendering at their exact coordinates, including the translation of the groups that contain the paths. A thin white halo behind the curves in panel (b) is only for legibility.

`check_modes_by_element.py` assigns every block to the path element that contains it and reports, per coding mode, the fill and stroke colours of those elements. In the example file mode 11 is used mostly for black-filled shapes (lettering and settlement symbols), and modes 01 and 10 mostly for district outlines, rivers and roads.

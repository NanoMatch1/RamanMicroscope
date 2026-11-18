# Stage 1 edge rerun, 2026-11-18: exploration scripts

One-off analysis of the second stage 1 edge session (stage 2's intermediate slit out, g2
following g1, TRIAX slit at 500 um). These scripts are not part of the application. They are
kept so that the findings they support can be re-run and checked: lab-notebook RAM-F5 (the edge
against g1, the slit series, the Ar-Hg frames) and RAM-F6 (the slit does not open symmetrically
about a fixed centre).

The data are not in git. Point `STAGE1_EDGE_DATA_DIRECTORY` at the folder holding `s1edge/`,
`s1step/`, `s1ref/` and the two run logs (the default is `scratch/2026-11-18`). Outputs (text
and PNG) go to `output/` here, which git ignores.

Run from the repository root:

```
PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
    explorations/stage1_edge_rerun_2026_11_18/<script>.py
```

Run `fit_edges.py` first (about 2-3 minutes): several of the others read its `fit_edges.json`
or import its functions.

| Script | What it shows |
|---|---|
| `inspect_frames.py` | Every frame's exposure, slit metadata, saturation and brightest rows. |
| `contact_sheets.py` | Thumbnails of the reference frames and of each centre. |
| `stray_light_and_band_profile.py` | The diffuse background and its scaling with slit width; the band's height and slant. |
| `fit_edges.py` | The edge fit of every frame: background removal, band sum, error-function edge. Also the per-centre slopes, single steps and backlash. |
| `edge_overlays_and_leakage.py` | Band spectra overlaid per centre, leakage past the closed edge, and the slit series. |
| `argon_lines_by_slit_width.py` | Ar-Hg line centroids at 50 and 500 um, in the lamp rows and the band rows. |
| `argon_line_shape_at_500um.py` | Ar line half-maximum points and widths at both slit widths. |
| `edge_against_g1_calibration.py` | The measured edge against the master calibration's g1 polynomial. |
| `single_reference_offset.py` | What one `referencegratings` leaves across the range; the cutoff in cm^-1 for a fixed spot offset. |
| `slit_symmetry_evidence.py` | The figure for RAM-F6: the Ar-Hg shift between slit widths against what a symmetric slit allows. |

"""
Calibration of the tunable filter's gratings: so far stage 1, with g1 against its cutoff edge
(g2 kept matched to it) and g2's pointing through a pinhole (issue #29).

The stage 1 edge is the cleaved edge of the laser-injection mirror. With a halogen lamp at the
sample, it shows on the CCD as a step in the spectrum, and its wavelength against the g1 count
is the g1 calibration. The run files take the frames; the analysis fits each edge, corrects
each centre's axis with an Ar-Hg frame, fits the calibration, runs gate checks, and writes a
report with plots and provenance; --apply writes it to the master calibration. Then, with g1
applied, g2 is stepped across a pinhole and its offset measured the same way (fit-g2). The
bench procedure and its reasoning: docs/stage1_edge_measurement.md.

Modules, in pipeline order:

- frame_names          the frame names the run files write and the analysis reads
- run_files            the run files (python -m filter_calibration plan)
- session              run logs and frame files back into FrameRecords
- edge_fit             the edge in one frame (background, band, error-function fit)
- axis_reference       the axis correction from an Ar-Hg frame at the same TRIAX position
- analysis             the session analysed: calibration fit, centres, steps, repeatability
- calibration_checks   the gates (registry: @edge_calibration_check)
- report, plots        report.txt, results.json with provenance, PNGs
- pinhole_scan         one g2 pinhole scan: light per frame along the tracked band, window fit
- g2_analysis          a g2 pinhole session: offset per centre, target band row, proposal
- g2_checks            the g2 gates (registry: @g2_pointing_check)
- g2_report, g2_plots  the g2 report.txt, results.json and g2_pinhole.png
- promotion            writing either result into the master calibration
- simulated_bench      a simulated stage 1 bench (lamp, edge, band, Ar-Hg lines, g2 pointing
                       and a pinhole) for tests and simulate mode

Everything except the run files' and the CLI's file writing is pure.
"""

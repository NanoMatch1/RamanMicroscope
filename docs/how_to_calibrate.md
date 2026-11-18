# How to calibrate

_Checked against git 17970d8 (feature/calibration-repeat-and-docs), 2026-11-18. Command syntax
comes from the code: `docs/command_reference.md` (generated from the docstrings) and
`python -m <package> --help`. If either disagrees with this page, the code is right and this
page is out of date._

This page says which calibrations the instrument has, in what order to do them, and the
commands for each. It is the starting point. The physics and the reasons behind each method are
in the guides it links to, so read those before changing a method.

## The calibrations, in order

Each one relies on those above it, so after a change, recalibrate from the first one the change
affects, then everything below it.

| # | Calibration | What it sets (master file group) | Run it when | State |
|---|---|---|---|---|
| 1 | Wavelength axis: TRIAX + PIXIS | `wavelength_axis` | the camera, TRIAX grating or TRIAX has moved or been swapped | ready |
| 1a | TRIAX re-zero | `wavelength_axis.triax_step_offset` | daily check; after a restart or lost TRIAX steps | ready |
| 2 | Live laser wavelength | nothing stored: read off the axis at each `sl` | automatic (`livecal` toggles it) | ready |
| 3 | Stage 1 edge: g1 (g2 follows) | `manual_g1`, `manual_g2` | after realigning stage 1, or when 1 moved the axis | ready; first full session pending |
| 4 | g2 pointing at stage 1's exit | `manual_g2` offset | after 3 | planned |
| 5 | Stage 2: g3/g4 | `manual_g3`, `manual_g4` | after realigning stage 2 | to follow (#29) |
| 6 | Polarisation response | not yet defined | before choosing the periscope geometry | to follow |

## How every calibration package works

The wavelength axis and the stage 1 edge follow the same pattern, and the ones still to come
will follow it too:

1. **Record.** Commands or run files take the data, and every frame and motor position is
   saved along with the conditions it was taken in: run logs in `data/runfile_logs/`, line
   walks in `data/calibration_line_walks/`.
2. **Fit offline, from the saved files.** The fit command reads only those files, so anyone can
   re-run it, on any computer, and get the same answer.
3. **Gates.** Every fit runs a list of checks and prints PASS, WARN (usable, but look) or FAIL.
   Each WARN or FAIL gives its evidence, the likely causes and what to try.
4. **Report.** Each fit writes a report and plots of the fit and its residuals (always, so
   they get looked at; `--no-plots` or `noplots` only for headless runs). The filter
   calibration also writes a `results.json`. The provenance is in both the report and the JSON: the software commit, the exact
   command line, and the SHA-256 of every input file. The command line re-runs the fit; the
   hashes say whether the inputs are still the same files.
5. **Apply.** Nothing in the master calibration changes until you apply. Applying refuses if any
   gate FAILs, backs up the master file to `calibration/backup/` first, and records what it
   wrote.

Send the report folder for review before applying.

## 1. Wavelength axis (TRIAX + PIXIS)

**What it does.** It gives every CCD pixel a wavelength, from the TRIAX position and the pixel
index. Everything else is measured on this axis.

**Method.** The Ar-Hg lamp's lines are walked across the chip at about 26 TRIAX positions. Lines
are identified by their pattern over the whole walk. The fit has two stages: first the CCD
terms, with a free offset for each frame, then a TRIAX polynomial through those offsets. Full
method: [calibration guide](calibration.md), section 3.

**Before you start.** Ar-Hg lamp at the TRIAX entrance slit, slit narrow (lines at most ~5 pixels
wide). Sensor below -30 C. Choose an exposure where 763.5, 811.5 and 912.3 nm stay below 65000
counts.

**Commands (in the application):**

```
acqtime <seconds>
speccal                              line walk, ~696-935 nm
                                     (speccal arhg samples=12: twice as many positions)
speccalfit curvature triaxorder=3
speccalapply curvature triaxorder=3  only if no gate failed
```

Reports and their plots go to `data/calibration_fit_reports/`. To fit saved walks outside the
application:

```
python -m wavelength_calibration fit data/calibration_line_walks/linewalk_*.json --curvature --triax-order 3
python -m wavelength_calibration fit <the same files> --curvature --triax-order 3 --apply
```

**1a. Re-zero.** `speccalzero check` measures how far the TRIAX zero has moved (about a minute)
without changing anything; use it as the daily check. `speccalzero` stores the shift, provided
every gate passes. If the frames disagree with each other, something more than the zero has
changed, and the report says to run the full calibration.

**Afterwards.** If the axis moved by more than a pixel or two, the grating calibrations were
measured against the old axis: redo 3.

## 2. Live laser wavelength

Nothing to calibrate. After each `sl`, the application takes a frame, finds the laser line and
reads its wavelength off the axis from 1. It is only as good as 1.

## 3. Stage 1 edge: g1, with g2 following

**What it does.** It sets g1 so stage 1's cutoff edge sits at the wavelength `sg` is given. g2
moves with g1 at the pairing ratio of the calibration in use.

**Method.** Halogen light through stage 1 is imaged on the CCD, with stage 2's intermediate slit
removed. g1 is stepped so the edge crosses the chip, at TRIAX centres from 720 to 920 nm, and
each frame's edge is fitted. Each centre's edges are corrected with Ar-Hg lines measured at that
centre's TRIAX position, with the slit at 50 um. A polynomial in the g1 count is then fitted
through the corrected edges. Full method, and why the edge rather than the laser spot:
[stage 1 edge guide](stage1_edge_measurement.md), sections 1-3.

**Before you start.** 1 applied, and `speccalzero check` passing the same day. Bench set-up (lamp,
aperture cards, TRIAX slit at ~500 um, stage 2's intermediate slit out, exposure): stage 1 edge
guide, section 4 "Set-up".

**Commands:**

```
python -m filter_calibration plan --exposure <s> --axis-exposure 15     writes 4 run files
```

Then, in the application, with the reference frames of step 0 taken by hand first:

```
runfile data/runfiles/stage1_edge_walk.txt          halogen, ~500 um
runfile data/runfiles/stage1_single_steps.txt
runfile data/runfiles/stage1_repeatability.txt
runfile data/runfiles/stage1_axis_references.txt    Ar-Hg, slit ~50 um
```

Then analyse, from the session's run logs (put the session's date in the pattern):

```
python -m filter_calibration fit data/runfile_logs/stage1_*_<YYYYMMDD>_*.txt
python -m filter_calibration fit <the same logs> --apply
```

**Reading the result.** The report folder is `data/filter_calibration_reports/stage1_edge_<time>/`.
Read the gates first. The calibration plot shows each run's residuals against the fit: the walk,
single steps and repeatability should all lie on it. The full list of what the report holds is
in section 5 of the stage 1 edge guide.

**Applying** writes `manual_g1` and `manual_g2` and appends a record to
`calibration/stage1_edge_calibration_history.json`.

**Not automated yet:** the laser's pointing offset from the edge (step 3 of the guide measures
it by hand), the per-row edge fit, and correcting the edge width for the Ar line width.

## 4. g2 pointing at stage 1's exit (planned)

With the current periscope, a g2 pointing error moves the band up or down the CCD. The
2026-11-18 walk shows that the pairing in use keeps g2's pointing consistent to within a step
across 720-920 nm. What remains is one absolute offset. The planned method puts a ~1 mm pinhole
at stage 1's exit, steps g2 across it, and uses the light reaching the CCD as the detector.

## 5. Stage 2: g3/g4 (to follow)

To be built on the same pattern as 3: issue #29.

## 6. Polarisation response (to follow)

The response of the instrument to each polarisation. It is needed before choosing the periscope
geometry, and it decides whether 4 can keep using the band row.

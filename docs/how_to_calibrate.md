# How to calibrate

_Checked against git 7f14a26 plus the g2 pinhole scan (feature/calibration-repeat-and-docs),
2026-11-18. Command syntax
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
| 4 | g2 pointing through a pinhole | `manual_g2` offset | after 3 is applied | ready; not yet run on the bench |
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
   they get looked at; `--no-plots` or `noplots` only for headless runs).
   - Every report records the provenance: the software commit that ran the fit, the exact
     command line, and the SHA-256 of every input file and of the master calibration it
     started from. The command line re-runs the fit; the hashes say whether the inputs are
     still the same files. The filter calibration also writes a `results.json`.
   - Each line walk also records the software version and conditions it was taken in.
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
python -m filter_calibration plan --exposure <s> --axis-exposure 15     writes the run files
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

## 4. g2 pointing through a pinhole

**What it does.** It sets where g2 points the beam leaving stage 1: one offset added to
`manual_g2`. How g2 follows g1 across wavelength is already right to under a step (RAM-F5).

**Method.** A ~1 mm pinhole sits on stage 2's entrance port axis. g2 alone is stepped across it
at three wavelengths, with the halogen through stage 1 and the CCD as the detector. The light
against g2 is a window, and its centre is where g2 points the beam through the pinhole. The
centre does not depend on the beam or pinhole size, or on how the CCD responds. The same scan
measures the band's rows per g2 step and its target row, and how well g1 and g2 are matched
across the chip. Full method and bench steps: stage 1 edge guide, section 4 step 4.

**Before you start.** 3 applied (the scan is measured against it). g2 set by hand with the laser
through a pinhole at stage 1's exit, then the relay aligned onto stage 2's axis, in that order
(step 4 of the guide). Camera reading the whole sensor (`roi full`, `roi binning software`).

**Commands:**

```
runfile data/runfiles/stage1_g2_pinhole_stage2.txt     pinhole on stage 2's entrance axis
runfile data/runfiles/stage1_g2_pinhole_stage1.txt     once, pinhole at stage 1's exit
python -m filter_calibration fit-g2 data/runfile_logs/stage1_g2_pinhole_*_<YYYYMMDD>_*.txt
python -m filter_calibration fit-g2 <the same logs> --apply
```

**Reading the result.** The report folder is `data/filter_calibration_reports/stage1_g2_<time>/`.
In `g2_pinhole.png`, each profile should be symmetric and the offsets should agree between
centres; the stage 1 exit scans should match the stage 2 ones. **Applying** adds the offset
to `manual_g2` (both directions) and records it in the same history file as 3.

## 5. Stage 2: g3/g4 (to follow)

To be built on the same pattern as 3: issue #29.

## 6. Polarisation response (to follow)

The response of the instrument to each polarisation. It is needed before choosing the periscope
geometry. The pinhole scan in 4 works in any geometry, but reading g2's pointing from the band
row (issues #37, #38) needs the current frame-flipping periscope.

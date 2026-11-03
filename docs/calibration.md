# Calibration guide

How the microscope knows what wavelength it is at, how to check it, and how to
recalibrate it. Written for whoever runs the instrument next; read sections 1
and 2 before changing any calibration.

> Status (November 2026): section 3 (the TRIAX + CCD wavelength axis) is the
> new procedure. The grating calibrations (section 5) are still the older
> method and are being rebuilt next, using the same pattern.

## 1. The chain of references

Every wavelength the instrument reports comes, directly or indirectly, from
one place: **the CCD wavelength axis**, which is built from the TRIAX
spectrometer position and the PIXIS pixel index.

```
known lines (Hg lamp, or Tiger measured on the spare spectrometer)
        |
        v
TRIAX + PIXIS wavelength axis      <- section 3: calibrate this first
        |
        v
live laser calibration             (Tiger peak read off the axis)
        |
        v
grating calibrations g1-g4         (filter and double monochromator)
        |
        v
Raman shift of every spectrum
```

Each stage is calibrated against the one above it, so an error near the top
propagates into everything below it, silently. The sections of the
instrument were designed to be calibrated independently and in this order.

Two rules follow:

1. **A calibration must be checked against something that does not depend on
   it.** See section 2 for specifics.
2. **Calibrate from the top down.** There is no point recalibrating the
   gratings against a wavelength axis that is itself wrong.

## 2. The circular reference (what went wrong after the camera swap)

After the Tucsen -> PIXIS swap, the pixel calibration was redone with
`tools/Calibrationgenerator.py`, using the wavelength and peak pixel reported
by the live laser calibration. The problem is that live calibration was
designed for a different job: correcting laser drift, on a sensor and
spectrometer that are already calibrated. It reads the laser peak off the
existing wavelength axis, which puts the TRIAX wavelength on pixel 50 and
counts outwards from there with the pixel calibration. So both numbers it
reports come out of the calibration being fitted, and fitting them can only
return the calibration that was already loaded.

The PIXIS has half the number of pixels of the Tucsen (1024 of 13 um, against
2048 of 6.5 um) across the same 13.3 mm chip width, so:

- **The slope came across correctly.** Doubling the nm per pixel to 0.07755
  is exactly right for pixels twice the size. It works out to ~6 nm/mm at the
  focal plane, as expected for a 300 g/mm grating in a 0.55 m spectrometer.
- **The offset didn't.** Pixel 50 is a Tucsen-era reference. If the PIXIS sits
  where the Tucsen did, Tucsen pixel 50 is physically PIXIS pixel 25, which
  shifts every wavelength by ~1.9 nm. A different mounting gives a different
  shift. Nothing in the loop could measure it.

The checks also found a small stretch: the axis was built with
`np.linspace(...)`, which spaced it 1024/1023 pixels apart (0.08 nm error at
the far edge). Fixed.

The new procedure avoids the loop. It measures line positions in raw pixels
and takes wavelengths only from an external reference.

## 3. The TRIAX + CCD wavelength axis

### 3.1 The model

```
wavelength(pixel, triax_steps) = triax_wavelength(triax_steps)
                                 + nm_per_pixel        * (pixel - reference_pixel)
                                 + nm_per_pixel_squared * (pixel - reference_pixel)^2
```

- `triax_wavelength(steps)` is the wavelength the TRIAX puts on the reference
  pixel. It is a polynomial in the TRIAX's own step count (linear in
  practice; the TRIAX controller's steps are close to linear in wavelength).
- `nm_per_pixel` is the dispersion: how many nm one pixel spans. Physically,
  the reciprocal linear dispersion of the spectrometer (nm per mm at the
  focal plane) times the pixel pitch.
- `nm_per_pixel_squared` is an optional curvature term. The dispersion is not
  quite constant across the chip because the diffraction angle changes
  across it; the effect is about 0.1-0.2 nm at the edges.
- `reference_pixel` is **chosen**, not fitted (see below). It stays at 50, the
  long-standing convention. It only defines where `triax_wavelength` is
  measured; where `st` puts a requested wavelength on the chip is a separate
  setting (section 3.5).

**Why the reference pixel can't be fitted.** Moving the reference pixel by
one pixel and shifting `triax_wavelength` by one pixel's worth of nm
describes exactly the same instrument. No data can tell those two apart, so
we fix one and fit the other.

**Why at least two different wavelengths are needed.** Walking one line
across the chip measures how many TRIAX steps move the line by one pixel.
That is a ratio of the TRIAX slope to the dispersion, not either one on its
own: a spectrometer with twice the dispersion and twice the TRIAX slope
produces identical data. A second known wavelength sets the scale. The fit
refuses single-wavelength data and says why.

**Why the inverse is computed, not fitted.** The old calibrations stored each
conversion and its inverse (`wl_to_g1` and `g1_to_wl`, ...) as two separately
fitted polynomials, so going wavelength -> steps -> wavelength didn't return
the starting value: up to ~0.3 nm on the gratings.
Now only the forward model is stored, and the inverse is computed from it
exactly.

### 3.2 Wavelength references

**Mercury lamp in second order (preferred).** The lab's mercury lamp is a UV
lamp with almost no near-infrared lines. But a grating sends wavelength
lambda in order m to the same angle as m * lambda in first order (grating
equation: m * lambda = d (sin a + sin b)). So the blue mercury lines appear
at twice their wavelength:

| Hg line (air) | appears at (2nd order) |
|---|---|
| 365.015 nm | 730.030 nm |
| 404.656 nm | 809.312 nm |
| 407.783 nm | 815.566 nm |
| 435.833 nm | 871.666 nm |

These wavelengths are known to ~0.002 nm, far better than the 0.078 nm a
pixel spans. The 809.3/815.6 pair is ~80 pixels apart, so both lines sit on
the chip at once. Things to check on the bench:

- Light the TRIAX entrance slit directly with the lamp. That calibrates the
  TRIAX + CCD alone and keeps the rest of the beam path out of it.
- Nothing between the lamp and the TRIAX may block blue light (a long-pass
  filter would remove the lines; that's the point of such filters).
- First-order lines (546.074, 576.960, 579.066 nm) are a useful cross-check
  at the short end of the range.

**Tiger laser + spare calibrated spectrometer (fallback, or cross-check).**
Read the Tiger wavelength on the spare spectrometer, then walk the laser line
across the PIXIS. Use at least three or four different Tiger wavelengths
spread over the range. Points taken at one Tiger wavelength all share that
wavelength's measurement error: more walk positions don't reduce it, more
distinct wavelengths do. Enter the spare spectrometer's real accuracy (its
specification, typically 0.1-0.5 nm), not its display resolution.

**A neon calibration bulb** (future purchase) has many strong first-order
lines between 700 and 900 nm and would be the most convenient reference.

### 3.3 The line walk

The procedure steps the TRIAX so each reference line lands on a series of
target pixels (100, 250, ..., 950). At each position it:

1. acquires a frame and collapses it to a spectrum, using rows around the
   brightest row (the image of the slit);
2. finds peaks more than 10 noise standard deviations above the background;
3. identifies which known line each peak is. The current calibration
   predicts roughly where each line should be. A common pixel shift is
   estimated from the first spectrum by matching the pattern of peaks, then
   refined from every line matched after that;
4. fits a Gaussian on a constant background to each identified line, **in
   pixels**, and records (known wavelength, TRIAX steps, centre pixel,
   centre uncertainty).

The TRIAX visits every position moving in the same direction (increasing
steps, after first backing off below the first position), so backlash in the
grating drive is the same for every point.

The current calibration is used only for planning and line identification.
The fit never sees it.

### 3.4 Fitting and accepting a calibration

The observations are fitted by weighted least squares. Each point's
uncertainty combines its reference-wavelength uncertainty with its fitted
peak-centre uncertainty, converted to nm. Before accepting a fit, look at:

- **residual rms and max**: a few hundredths of a nm is good for mercury
  lines. A residual of several nm on one line means it was misidentified
  (one mercury line mistaken for its neighbour).
- **reduced chi-squared**: ~1 means the scatter matches the stated
  uncertainties. Much larger than 1 means the uncertainties are optimistic
  or the model is missing something; try the curvature term. (With
  Tiger + spare-spectrometer data it varies a lot from run to run, for the
  shared-error reason above.)
- **the change from the current calibration**: the report gives the largest
  difference across the chip. Expect an offset of up to a few nm the first
  time (section 2). After that, a large change means something moved.

### 3.5 Running it on the instrument

**With the mercury lamp:**

1. Point the lamp at the TRIAX entrance slit. Narrow the slit (sharp lines
   fit better) but keep the lines well above the noise.
2. Set an acquisition time that gives strong lines without saturating
   (`acqtime <seconds>`). Single frames are fine.
3. Run `speccal hg`. The TRIAX walks the 730, 809, 816 and 872 nm lines
   across the chip, about 28 positions. Each walk is saved to
   `data/calibration_line_walks/linewalk_<date>_<time>_hg.json` and added
   to this session's list.
4. Run `speccalfit` and read the report (section 3.4). If the reduced
   chi-squared is well above 1, try `speccalfit curvature`.
5. If it looks right, run `speccalapply` (or `speccalapply curvature`).
   This backs up the master file to `calibration/backup/`, writes the new
   `wavelength_axis` group, and reloads it straight away.

**With the Tiger and the spare spectrometer:**

1. Tune the Tiger, then read its wavelength on the spare spectrometer.
2. With the laser reaching the TRIAX (attenuated: the CCD saturates
   easily), run `speccal external <wavelength_nm> <uncertainty_nm>`, e.g.
   `speccal external 785.12 0.2`.
3. Repeat at three or four more Tiger wavelengths spread over the range
   you use. Each walk is added to the session.
4. `speccalfit`, then `speccalapply`, as above.

Walks from one session are fitted together, so mercury and Tiger walks can
be combined. `speccalreset` starts a new list. Saved walks can also be
fitted later, outside the application:

```
python -m wavelength_calibration fit data/calibration_line_walks/linewalk_*.json
python -m wavelength_calibration fit <files> --curvature --apply
```

**After applying:** the live laser calibration and all spectra use the new
axis immediately. If the offset changed by more than a pixel or two, the
grating calibrations were made against the old axis and should be checked
next (section 5).

**What `st <wavelength>` does.** It moves the TRIAX so the requested
wavelength lands on CCD pixel 100 (`spectrometer_target_pixel` in
`microscope_config.json`). Set to the laser wavelength, that leaves ~8 nm of
margin below the laser line and the rest of the chip (~72 nm) for the Stokes
spectrum. Before November 2026, `st` stopped a fixed 1910 steps short
instead, which put the requested wavelength on pixel ~274 of the PIXIS.
The wavelength axis is always computed from where the TRIAX actually is, so
this setting only changes where things land on the chip, never which
wavelength a pixel reads.

### 3.6 Simulate mode

In simulate mode, `speccal hg` runs against a simulated mercury lamp. The
lamp has its own "true" calibration, ~2 nm away from the shipped one, so
you can practise the whole procedure and watch it find the offset. The
headless test suite runs exactly this workflow
(`test_wavelength_axis_line_walk_recovers_simulated_truth`).

The simulator holding its own truth matters. The older simulated camera
placed the laser line using the software's own wavelength axis, so in
simulation every calibration looked perfect.

### 3.7 Where the code lives

| File | Role |
|---|---|
| `wavelength_calibration/reference_lines.py` | mercury line table, diffraction orders, external references |
| `wavelength_calibration/line_peaks.py` | peak finding and Gaussian fits, in pixels |
| `wavelength_calibration/line_walk.py` | the procedure; hardware passed in as three functions |
| `wavelength_calibration/wavelength_axis_model.py` | the model, its exact inverse, the weighted fit |
| `wavelength_calibration/promotion.py` | fit saved walks, compare, write the master file |
| `wavelength_calibration/simulated_line_lamp.py` | lamp + spectrometer simulator |
| `calibration.py` (`_load_wavelength_axis_model`) | loads the model at startup |
| `microscope.py` (`speccal*` commands) | connects the procedure to the TRIAX and PIXIS |
| `test_wavelength_calibration.py` | unit tests, including recovery from a wrong start |

In the master file, `wavelength_axis` replaced the old `camera_calibrations`
(`pixel_to_wl`, `wl_to_pixel`) and `triax_calibrations` (`triax_to_wl`,
`wl_to_triax`) groups. The values were carried over unchanged, with
`verified_against_external_reference: false` until a line walk is applied.
While that flag is false, the application logs a warning at startup.

## 4. Order of work after a hardware change

1. Wavelength axis (section 3), whenever the camera, the TRIAX grating or
   the TRIAX itself has been moved or swapped.
2. Live laser calibration then works on its own (it reads the axis).
3. Gratings (section 5), after realignment or if section 3 moved the axis.

## 5. Grating calibrations (g1-g4)

Being rebuilt next. Physical facts the new fits will use:

- g1/g2 are 1200 g/mm, g3/g4 are 300 g/mm. (g1/g2 used to be called g3/g4
  when the instrument had only one double monochromator section.)
- Each pair is a matched double-subtractive arrangement, so the two gratings
  of a pair share one calibration curve, mirrored in sign.
- The calibration curve (diffraction plus alignment) is stable. What drifts
  is the offset, which `referenceall` and `calhome` reset.

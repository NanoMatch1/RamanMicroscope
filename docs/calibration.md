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
known lines (Ar-Hg lamp, or Tiger measured on the spare spectrometer)
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
                                 + nm_per_pixel_at(triax_steps) * (pixel - reference_pixel)
                                 + nm_per_pixel_squared          * (pixel - reference_pixel)^2

nm_per_pixel_at(triax_steps) = nm_per_pixel
                               + nm_per_pixel_change_per_triax_step
                                 * (triax_steps - dispersion_reference_triax_steps)
```

- `triax_wavelength(steps)` is the wavelength the TRIAX puts on the reference
  pixel. It is a polynomial in the TRIAX's own step count: linear for short
  walks, quadratic over the full Ar-Hg range (explained below).
- `nm_per_pixel` is the dispersion: how many nm one pixel spans. Physically,
  the reciprocal linear dispersion of the spectrometer (nm per mm at the
  focal plane) times the pixel pitch. It is the value at
  `dispersion_reference_triax_steps` (the middle of the calibration walk).
- `nm_per_pixel_change_per_triax_step` is how the dispersion changes as the
  grating turns (explained below). It is small, about -2e-8 nm per pixel per
  step, but it matters over a 690-930 nm walk.
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

**Why the dispersion depends on the TRIAX position.** The dispersion comes
from the grating equation. Differentiating m * lambda = d (sin a + sin b) at
a fixed incidence angle a gives d(lambda)/d(b) = d cos(b) / m, so one
pixel (a fixed step in b, since pixel pitch / focal length is fixed) spans

```
nm_per_pixel = d * cos(b) * pixel_pitch / (m * focal_length)
```

where d is the groove spacing (3333 nm for 300 g/mm) and b the diffraction
angle. Turning the grating to longer wavelengths increases b, so cos(b) and
the nm per pixel fall. For the 300 g/mm grating, the 550 mm focal length and
13 um pixels, that is about 0.0777 nm/px at 700 nm and 0.0773 at 900 nm. The
first Ar-Hg walk on the bench showed the same trend (0.0774 -> 0.0771).

A 0.5 % change sounds negligible, but at the far edge of the chip, ~950
pixels from the reference pixel, it is 0.3-0.4 nm across the walk. A single
nm_per_pixel can only split the difference: ~0.04 nm rms and up to ~0.15 nm
of error at the chip edges. Bright lamp lines are fitted to ~0.01 pixel, so
that error shows up as a reduced chi-squared in the hundreds or thousands.

Two smaller effects of the same geometry come with it:

- **The TRIAX steps turn the grating angle, not the wavelength.** The
  wavelength on the reference pixel goes as sin(grating angle), so it is
  slightly curved in steps: about 0.2 nm away from a straight line at the
  ends of a 690-930 nm walk. A quadratic `triax_wavelength` (option
  `triaxquadratic`) takes it up.
- **The focal plane is flat.** Pixels are evenly spaced in distance, not in
  angle, so the dispersion also changes slightly across the chip at one
  grating position. That is the `curvature` term.

In a physical model of the TRIAX (grating equation, 550 mm focal length,
flat focal plane, steps linear in grating angle), a 690-930 nm walk needs
all three terms together: with any one or two of them the reduced
chi-squared stays in the hundreds, and with all three it is ~0.2. For the
Ar-Hg walk, fit with `speccalfit curvature triaxquadratic` (the dispersion
term is on by default).

**Why the inverse is computed, not fitted.** The old calibrations stored each
conversion and its inverse (`wl_to_g1` and `g1_to_wl`, ...) as two separately
fitted polynomials, so going wavelength -> steps -> wavelength didn't return
the starting value: up to ~0.3 nm on the gratings.
Now only the forward model is stored, and the inverse is computed from it
exactly.

### 3.2 Wavelength references

**Argon-mercury lamp (preferred).** The lab's calibration lamp is an Ar-Hg
pencil lamp. Its label lists 17 argon lines between 696 and 922 nm, which
covers the instrument's working range in first order. The wavelengths are
known to ~0.005 nm, far better than the 0.078 nm a pixel spans.

The catalogue, `ARGON_MERCURY_LAMP_LINES` in
`wavelength_calibration/reference_lines.py`, lists the lines this lamp
**actually shows on this instrument**. It is based on the first bench walk
(November 2026, 690-910 nm):

- **Lines that aren't on the label are in it.** Argon lines at 714.704,
  751.465, 801.479, 810.369 and 840.821 nm aren't listed on the label, and
  some sit 11-21 pixels from a listed line. They're in the catalogue so they
  can't be mistaken for their listed neighbours, and they're good references
  in their own right.
- **Lines the lamp doesn't show are left out.** Ar 710.748 is on the label
  but wasn't seen. A grating also sends wavelength lambda in order m to the
  same angle as m * lambda in first order, so mercury's blue and UV lines
  could appear among the argon lines in second and third order (730.0,
  760.96, 809.31, 815.57 nm, ...). None of them were seen, presumably because
  the lamp envelope or the optics absorb the UV. A line in the catalogue
  that isn't really there is a target that an unrelated weak peak can be
  matched to, so these are out.
- **One weak line at ~871.6 nm** matches Hg 435.833 in second order. It is
  kept for identification but not used as a reference until it's confirmed.
- **772.376 and 772.421 nm are an unresolved pair** (0.6 pixel apart). They
  look like one line, but the fitted centre would be a brightness-weighted
  blend, so neither is used.
- 912.297 and 922.450 nm were beyond the frames recorded so far: expected,
  not yet confirmed.

If a walk shows a line that isn't in the table, or keeps missing one that
is, edit the table. It's the only place the lamp's lines are defined.

Light the TRIAX entrance slit directly with the lamp. That calibrates the
TRIAX + CCD on their own and keeps the rest of the beam path out of it.

**Tiger laser + spare calibrated spectrometer (cross-check).** Read the Tiger
wavelength on the spare spectrometer, then walk the laser line across the
PIXIS. Use at least three or four different Tiger wavelengths spread over
the range. Points taken at one Tiger wavelength all share that wavelength's
measurement error: more walk positions don't reduce it, more distinct
wavelengths do. Enter the spare spectrometer's real accuracy (its
specification, typically 0.1-0.5 nm), not its display resolution.

### 3.3 The line walk

The CCD spans ~79 nm. The TRIAX slides it across the range of the reference
lines in steps of 1/6 of its width (about 25 positions for the Ar-Hg lamp),
so each line is measured at about six places across the chip. At each
position the procedure:

1. acquires a frame and collapses it to a spectrum, using rows around the
   brightest row (the image of the slit). A column with any saturated pixel
   in that band is marked as saturated;
2. finds peaks more than 10 noise standard deviations above the background;
3. identifies which known line each peak is. The current calibration
   predicts roughly where every line in the catalogue should be. A common
   pixel shift is found on the first usable spectrum by pattern matching
   (the shift that lines up the most peaks with predictions, within 3
   pixels), then refined from every line matched after that;
4. fits a Gaussian on a constant background to each identified line, **in
   pixels**, and records (known wavelength, TRIAX steps, centre pixel,
   centre uncertainty).

A line is used at a position only if all of these hold, and the reason is
recorded whenever one fails:

- no other catalogue line is predicted within 8 pixels (closer lines blend);
- the nearest peak is within 4 pixels of the prediction, and that peak's
  nearest predicted line is this one (mutual nearest neighbours);
- the peak isn't saturated (a clipped top biases the centre). If a strong
  line is skipped for saturation, shorten the exposure, or accept losing it
  if plenty of other lines were measured;
- the fit succeeds and passes the signal-to-noise threshold.

The fit window is narrowed to half the distance to the nearest other peak,
so a neighbour's tail stays out of it.

**The catalogue has to match the lamp.** A line the walk doesn't know about
can be mistaken for a known one nearby, and a catalogue line the lamp
doesn't emit can be matched to an unrelated peak. If you change lamps,
build the new catalogue from a real walk: the saved file keeps every
spectrum (section 3.5), so you can see exactly what the lamp shows.

The TRIAX visits every position moving in the same direction (increasing
steps, after first backing off below the first position), so backlash in the
grating drive is the same for every point. If the TRIAX isn't at the
requested position when it's read back, that position is skipped rather than
measured while the grating might still be moving.

The current calibration is used only for planning and line identification.
The fit never sees it.

### 3.4 Fitting and accepting a calibration

The observations are fitted by weighted least squares. Each point's
uncertainty combines its reference-wavelength uncertainty with its fitted
peak-centre uncertainty, converted to nm. Before accepting a fit, look at:

- **residual rms and max**: a few hundredths of a nm is good for lamp
  lines. A residual of ~1 nm or more on one line means it was misidentified
  (mistaken for a neighbour); the report flags it.
- **reduced chi-squared**: ~1 means the scatter matches the stated
  uncertainties. Much larger than 1 means the uncertainties are optimistic
  or the model is missing something. A small rms with a chi-squared in the
  thousands is what a missing model term looks like (section 3.1). (With
  Tiger + spare-spectrometer data it varies a lot from run to run, for the
  shared-error reason above.)
- **the residual table in the saved report**: residuals that follow a
  pattern (with TRIAX position, or across the chip) point to a missing
  model term; one line that is off on its own points to a misidentification.
- **the change from the current calibration**: the report gives the largest
  difference across the chip. Expect an offset of up to a few nm the first
  time (section 2). After that, a large change means something moved.

### 3.5 Running it on the instrument

**With the Ar-Hg lamp:**

1. Point the lamp at the TRIAX entrance slit. Narrow the slit: the closest
   pairs used are 11-15 pixels apart and need lines no more than ~5 pixels
   wide.
2. Set an acquisition time where the brightest lines (763.5 and 811.5 nm)
   are close to, but below, saturation (`acqtime <seconds>`). Single frames
   are fine.
3. Run `speccal` (or `speccal arhg`). The TRIAX slides the chip from ~690
   to ~930 nm, about 25 positions. Each walk is saved to
   `data/calibration_line_walks/linewalk_<date>_<time>_arhg.json` and added
   to this session's list. Set the logging level to DEBUG to see why each
   skipped line was skipped. The reasons are also saved in the file, with
   the spectrum from every position.
4. Run `speccalfit curvature triaxquadratic` and read the report
   (section 3.4). This is the full model of section 3.1; the dispersion is
   fitted as changing with the TRIAX position by default. Options can be
   given in any order: `curvature`, `triaxquadratic`, and
   `fixeddispersion` (holds the dispersion fixed; only sensible for a walk
   spanning a few tens of nm).
5. If it looks right, run `speccalapply` with the same options. This backs
   up the master file to `calibration/backup/`, writes the new
   `wavelength_axis` group, and reloads it straight away.

Every `speccalfit` and `speccalapply` saves its report to
`data/calibration_fit_reports/wavelength_axis_fit_<date>_<time>.txt`. The
report includes the line walks used, the fitted terms, every point's
residual, the fitted model, and a status line: `NOT APPLIED`, or `APPLIED`
with the master file and its backup. An applied model names its report in
its metadata (`fit_report`), so the calibration in use can always be traced
back to the fit that produced it.

**With the Tiger and the spare spectrometer:**

1. Tune the Tiger, then read its wavelength on the spare spectrometer.
2. With the laser reaching the TRIAX (attenuated: the CCD saturates
   easily), run `speccal external <wavelength_nm> <uncertainty_nm>`, e.g.
   `speccal external 785.12 0.2`.
3. Repeat at three or four more Tiger wavelengths spread over the range
   you use. Each walk is added to the session.
4. `speccalfit`, then `speccalapply`, as above.

Walks from one session are fitted together, so lamp and Tiger walks can be
combined. `speccalreset` starts a new list. Saved walks can also be
fitted later, outside the application:

```
python -m wavelength_calibration fit data/calibration_line_walks/linewalk_*.json
python -m wavelength_calibration fit <files> --curvature --triax-quadratic --apply
```

These save their report in the same place (`--report-directory` to
change it). `--fixed-dispersion` is the equivalent of `fixeddispersion`.

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

In simulate mode, `speccal` runs against a simulated Ar-Hg lamp: every
catalogue line, at uneven brightness, clipped at the CCD's full scale. The
lamp has its own "true" calibration, ~2 nm away from the shipped one, so
you can practise the whole procedure and watch it find the offset. The
headless test suite runs exactly this workflow
(`test_wavelength_axis_line_walk_recovers_simulated_truth`).

The simulator holding its own truth matters. The older simulated camera
placed the laser line using the software's own wavelength axis, so in
simulation every calibration looked perfect.

The truth also has to be physically complete. Until November 2026 the
simulated spectrometer had a constant dispersion, so the simulated walk
passed while the first real one gave a reduced chi-squared above 5000
(section 3.1). Its truth now includes the dispersion change with TRIAX
position, and `test_fixed_dispersion_cannot_describe_a_wide_walk` checks
that a fixed-dispersion fit is caught.
`test_grating_angle_drive_needs_the_full_physical_model` adds the
sin(grating angle) drive and checks that only the full model recovers it.
The simulator used by `speccal` in simulate mode doesn't include the
quadratic drive yet.

### 3.7 Where the code lives

| File | Role |
|---|---|
| `wavelength_calibration/reference_lines.py` | Ar-Hg lamp line catalogue (the lines this lamp shows, blends marked), external references |
| `wavelength_calibration/line_peaks.py` | peak finding and Gaussian fits, in pixels |
| `wavelength_calibration/line_walk.py` | the procedure; hardware passed in as three functions |
| `wavelength_calibration/wavelength_axis_model.py` | the model, its exact inverse, the weighted fit |
| `wavelength_calibration/promotion.py` | fit saved walks, compare, write the fit report and the master file |
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

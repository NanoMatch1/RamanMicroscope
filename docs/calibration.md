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
chi-squared stays in the hundreds, and with all three it is ~0.2.

The real TRIAX departs further from that model than the sine alone: over the
full walk (87000-121000 steps) the wavelength on the reference pixel is ~0.3
nm from any quadratic in steps, and needs a cubic to get to ~0.1 nm (2026-11-10
data, section 3.4). Fit the Ar-Hg walk with `speccalfit curvature
triaxorder=3` (the dispersion term is on by default); the TRIAX-shape gate
reports which order the data supports.

**Why the inverse is computed, not fitted.** The old calibrations stored each
conversion and its inverse (`wl_to_g1` and `g1_to_wl`, ...) as two separately
fitted polynomials, so going wavelength -> steps -> wavelength didn't return
the starting value: up to ~0.3 nm on the gratings.
Now only the forward model is stored, and the inverse is computed from it
exactly.

### 3.2 Wavelength references

**Argon-mercury lamp (preferred).** The lab's calibration lamp is an Ar-Hg
pencil lamp. Its argon lines cover the instrument's working range in first
order, and their wavelengths are known to ~0.001 nm (NIST), far better than
the 0.077 nm a pixel spans.

The line table, `ARGON_MERCURY_LAMP_LINES` in
`wavelength_calibration/reference_lines.py`, has two jobs, so it holds two
kinds of line:

- **Every line that can reach the chip, for identification.** During a walk
  the chip edges span about 615-1015 nm. The table lists every NIST line in
  that range: argon (NIST relative intensity 50 or more), mercury in first
  order, and mercury from 300-515 nm in second order (a grating sends
  wavelength lambda in order m to the same angle as m * lambda in first
  order, so Hg 404.657 nm appears at 809.31 nm). A line missing from the
  table is invisible to the identification, and a peak from it can be taken
  for a listed line nearby. That is exactly what went wrong on 2026-11-10
  (section 3.3).
- **Confirmed lines, for fitting** (`usable_as_reference`). Only argon lines
  that were seen on this instrument, aren't blends, and agree with the other
  lines in the same frames to better than 0.01 nm are fitted. Mercury is
  identification-only: on 2026-11-10 every mercury line, first and second
  order, sat 0.03-0.06 nm away from where the argon lines in the same frame
  put it, while the argon lines agreed to 0.007 nm. The NIST values are
  right, so the offset is instrumental (probably the two gases lighting the
  entrance slit differently).
- **Lines too close to separate** (closer than ~0.2 nm) are one peak on this
  CCD. If one is far brighter than the other (Ar 706.722 and the 100x weaker
  706.874), it stands for the pair; otherwise the pair is a blend, used for
  identification only (Ar 772.376 + 772.421).

If the gate report shows a strong peak that no listed line explains, it
gives the peak's wavelength: look it up in NIST (air wavelengths, and half
the wavelength for second order) and add it to the table.

Light the TRIAX entrance slit directly with the lamp. That calibrates the
TRIAX + CCD on their own and keeps the rest of the beam path out of it.

**Tiger laser + spare calibrated spectrometer (cross-check).** Read the Tiger
wavelength on the spare spectrometer, then walk the laser line across the
PIXIS. Use at least three or four different Tiger wavelengths spread over
the range. Points taken at one Tiger wavelength all share that wavelength's
measurement error: more walk positions don't reduce it, more distinct
wavelengths do. Enter the spare spectrometer's real accuracy (its
specification, typically 0.1-0.5 nm), not its display resolution.

### 3.3 The line walk and line identification

The CCD spans ~79 nm. The TRIAX slides it across the range of the reference
lines in steps of 1/6 of its width (about 26 positions for the Ar-Hg lamp),
so each line is measured at about six places across the chip. The plan comes
from the calibration in use, with 3 nm of margin at each end in case that
calibration is off.

**The walk only acquires.** At each position it records the spectrum (the
mean of a band of rows centred on the slit image; the band is fixed by the
first frame, so a tilted slit image can't move the lines from frame to
frame), the time, the sensor temperature and the TRIAX position. A column
with a saturated pixel is marked saturated. If the TRIAX isn't at the
requested position when read back, the position is skipped. Positions are
visited in increasing steps after backing off below the first, so backlash
is the same for every point.

**Lines are identified from all the spectra at once, by pattern**
(`wavelength_calibration/line_identification.py`):

1. Every peak in every spectrum is found and fitted (a Gaussian on a
   constant, in pixels). A fit whose centre runs more than 1.5 pixels from
   the peak it started on is dropped: on broad lines, a bump on a bright
   line's wing was otherwise fitted as a false peak 2-3 pixels from the line
   (2026-11-11).
2. For each frame and each wavelength offset of the calibration in use
   (+/-12 nm), count how many of the frame's strong peaks would then sit
   within 0.15 nm of a line in the table.
3. Identify the walk as a whole: the offset may drift linearly along the
   walk (the calibration in use has a slope error) and each frame may wander
   0.5 nm from that trend (the TRIAX drive). The trend that explains the
   most strong peaks over the whole walk wins; frames with few lines are
   carried by their neighbours. The best identification more than ~1 nm away
   is reported too: if it explains nearly as many peaks, the identification
   is ambiguous and the gates say so.
4. Each frame is refined around the trend, every peak is matched to its
   mutually nearest line, and a pixel -> wavelength map is fitted to the
   frame's reference lines. A second pass repeats this with the walk's own
   map shape, so a frame with only two lines takes its dispersion from its
   neighbours.
5. Each frame is checked on its own: every strong peak must be explained,
   and the lines must agree with one map to 0.03 nm. A correctly identified
   frame agrees to ~0.005 nm; a misidentified line is ~1 nm off, so a wrong
   identification cannot pass quietly. A line far off the others (a weak or
   blended peak) is dropped from that frame with the reason recorded. A frame
   with one line is used when the rest of the walk fixes the pattern and no
   other listed line is within reach.
6. Frames the trend doesn't reach are tried again from their neighbours,
   working outward from the identified frames: each is searched around the
   offset its two nearest identified frames predict. The calibration in use
   can bend away from a straight trend at the ends of the walk (on
   2026-11-11 it was 0.5-1.7 nm off in the last frames), and without this
   step those frames failed and the fit extrapolated over them. Such frames
   pass the same checks, and the report says they were identified this way.

Only confirmed reference lines that are unsaturated, at least 15 pixels from
the chip edges and not blended with a listed neighbour become measurements.
Each measurement's centre uncertainty includes a floor of 0.05 pixel: the
Gaussian fit's own uncertainty ignores photon noise and line shape and is
10-1000x too small for bright lines.

**Why not "the peak nearest the prediction".** The first version predicted
each line's pixel from the calibration in use and took the nearest peak
within 4 pixels. That calibration was off by 8-37 pixels, by an amount that
changed along the walk, so a weak neighbour often sat closer to the
prediction than the line itself. In the 2026-11-10 walks, 72 of the 91
recorded lines were the wrong line (for example Hg 404.657 in second order,
recorded as Ar 811.531), which is why the fit's reduced chi-squared was in
the thousands. Repeated walks repeated the same mistake, so no consistency
check across walks could see it. The saved walks are re-identified with the
new method: `test_wavelength_calibration.py` replays one of them.

The walk file keeps every spectrum, and `speccalfit` always re-identifies
from the spectra, so old walks benefit from any later improvement to the
table or the method.

### 3.4 Fitting, the gates, and accepting a calibration

**The fit has two stages.** First the CCD terms (dispersion, its change with
TRIAX position, curvature), with a free wavelength offset for every frame.
Then the TRIAX polynomial through those frame offsets. In a single joint fit,
any TRIAX error the polynomial can't follow leaks into the shared CCD terms
and bends the whole axis; with a free offset per frame it can't. Several
walks are fitted together with one zero per walk, so walks taken before and
after the TRIAX zero moved still share the shape fit. The stored zero is the
latest walk's. A walk with one line per frame (an external laser) can't
separate the two, and is fitted in one stage.

**The gates.** Every fit runs the checks in
`wavelength_calibration/calibration_checks.py` and prints a verdict for
each: PASS, WARN (usable, but look), or FAIL (`speccalapply` refuses). Every
WARN and FAIL comes with its evidence, the likely causes and what to try.
Most of them read the residuals split in two:

- **within each frame** (CCD axis, identification, table wavelengths): on
  the 2026-11-10 data, correctly identified, ~0.005 nm;
- **between frames** (TRIAX): what the TRIAX polynomial can't follow.

| Check | What it catches |
|---|---|
| walk data | walks recorded in simulate mode, walks without metadata, mixed software versions |
| instrument conditions | sensor warmer than -30 C or drifting, exposure changed between walks |
| line identification | an ambiguous pattern match; the calibration in use near the edge of the search range |
| frames identified | frames that failed, with each frame's reason |
| unexplained peaks | strong peaks no listed line explains, by wavelength |
| fit made | not enough identified lines to fit |
| CCD axis (within-frame) | lines in one frame disagreeing (misidentification, saturation, missing curvature term) |
| line bias | one line consistently off the others (wrong table value, a blend, another species) |
| TRIAX shape | the TRIAX polynomial too stiff (the report gives the order the data needs) or the drive itself |
| walk agreement | the TRIAX zero moving between walks, walks not repeating, a walk drifting as the instrument warms up |
| coverage | lines seen too rarely, gaps, unidentified frames at a walk's ends (extrapolated) |
| saturation | reference lines lost to saturation, with the exposure used |
| fit statistics | chi-squared, and what it is measuring |
| change from calibration in use | a big change (check the grating calibrations afterwards) |

Limits are in `CheckLimits`. A check is one decorated function: write it in
`calibration_checks.py` and every report runs it.

**What the 2026-11-10 data says** (six afternoon walks, re-identified): the
CCD axis agrees to 0.007 nm within frames; the walks repeat to 0.03 nm (~3
TRIAX steps) once the first walk, which drifted by up to 0.19 nm at its
start, is set aside; and the TRIAX is not a low-order polynomial in steps
over 87000-121000 steps (rms about a quadratic 0.34 nm, about a cubic 0.10
nm, order 5 0.05 nm). Use `triaxorder=3` for the full walk. What no
polynomial follows (about 0.1 nm from one calibration position to the next,
the same in every walk) is a property of the drive; a TRIAX position table
would capture it.

### 3.5 Running it on the instrument

**With the Ar-Hg lamp:**

1. Point the lamp at the TRIAX entrance slit. Narrow the slit: the closest
   pairs used are 11-15 pixels apart and need lines no more than ~5 pixels
   wide.
2. Wait until the sensor is below -30 C. Set an acquisition time where the
   brightest lines (763.5, 811.5 and 912.3 nm) stay below 65000 counts
   (`acqtime <seconds>`). Saturated lines are lost as references, and the
   saturation gate reports how many. Single frames are fine.
3. Run `speccal` (or `speccal arhg`). It first takes one frame of the whole
   sensor, finds the slit image and records where it is (rows, width,
   tilt); if the camera ROI misses it, an automatic ROI is set. Then the
   TRIAX slides the chip over the lines from ~696 to ~935 nm, about 26
   positions. Each walk is saved to
   `data/calibration_line_walks/linewalk_<date>_<time>_arhg.json` with every
   spectrum and the conditions it was taken in (software version, simulate
   mode, exposure, frames averaged, sensor temperature per frame, TRIAX
   position before the walk), and added to this session's list. The log
   gives the identification summary and any frame that wasn't identified,
   with the reason. `speccal arhg samples=12` walks in half-size steps, so each
   line is seen at ~12 places on the chip instead of 6 (twice the positions
   and the time); use it to see how the TRIAX behaves between the usual
   positions.
4. Run `speccalfit curvature triaxorder=3` and read the gate report
   (section 3.4). Options, in any order: `curvature`; `triaxquadratic` or
   `triaxorder=N` (the TRIAX-shape gate suggests N); `fixeddispersion`
   (only for a walk spanning a few tens of nm); `triaxsigma=S` (adds a TRIAX
   error to every point, after which chi-squared no longer tests the fit;
   the fit-statistics gate says so); `plot` (also saves a picture of the
   fit and its residuals, below).
5. If no gate fails, run `speccalapply` with the same options. It backs up
   the master file to `calibration/backup/`, writes the new
   `wavelength_axis` group, and reloads it straight away. If a gate fails it
   refuses, and the report says why.

Every `speccalfit` and `speccalapply` saves its report to
`data/calibration_fit_reports/wavelength_axis_fit_<date>_<time>.txt`: the
status (`NOT APPLIED`, `NOT APPLIED: a gate check failed`, or `APPLIED`
with the master file and its backup), every gate with its evidence and
advice, the fitted terms, each walk's frame-by-frame identification, every
residual, and the model. An applied model names its report in its metadata
(`fit_report`), stores the TRIAX position table for the re-zero
(`triax_position_offsets_nm`), and records the TRIAX range it was fitted over
(`calibrated_triax_drive_steps`). Outside that range the TRIAX polynomial is
extrapolated, and the application logs a warning whenever the TRIAX is
there: on 2026-11-11 an order-5 fit was off by up to 1.7 nm within 4000
steps of its last fitted position.

**The fit plot** (`speccalfit ... plot`, `speccalapply ... plot`, or
`--plot` on the command line) is saved next to the report, with the same
name and `.png`. Its four panels follow the same split as the gates:

- *TRIAX map*: the wavelength each frame puts on the reference pixel, with
  the fitted TRIAX polynomial (each walk's zero removed, so all walks sit on
  one curve).
- *TRIAX residual*: each frame's offset from that curve. A pattern repeated
  by every walk belongs to the TRIAX drive; one walk off the others is that
  walk's zero or warm-up.
- *CCD axis*: each line's residual within its frame, against pixel. A slope
  or bow across the chip means a CCD term is missing or the dispersion
  changed; scatter well above 0.01 nm means misidentification or saturation.
- *Residual by line*: each reference line's within-frame residuals and their
  mean. One line sitting off the others is a wrong table wavelength or a
  blend.

**After the TRIAX step count moves: `speccalzero`.** If the TRIAX is
re-initialised or loses steps, every wavelength shifts by the same number
of steps while the shape of the calibration stays. `speccalzero` revisits
three of the calibration walk's TRIAX positions (about a minute), measures
the shift in steps, and, if every gate passes, stores it in the calibration
in use as `triax_step_offset` (backed up first). Because it goes back to the
calibration's own positions and knows what the drive did there
(`triax_position_offsets_nm`), the drive pattern doesn't bias it; a shift of
more than 10 steps is measured again at the corrected positions. If the
frames disagree on the shift, more than the zero has changed (optics,
grating) and the report says to run the full calibration. `speccalzero
check` measures and reports without changing anything, which makes a quick
daily check. Its reports are saved as
`data/calibration_fit_reports/triax_zero_<date>_<time>.txt`.

**With the Tiger and the spare spectrometer:**

1. Tune the Tiger, then read its wavelength on the spare spectrometer.
2. With the laser reaching the TRIAX (attenuated: the CCD saturates
   easily), run `speccal external <wavelength_nm> <uncertainty_nm>`, e.g.
   `speccal external 785.12 0.2`. In each frame the laser must be the
   dominant peak (5x the next) to be used.
3. Repeat at three or four more Tiger wavelengths spread over the range
   you use. Each walk is added to the session.
4. `speccalfit`, then `speccalapply`, as above.

Walks from one session are fitted together, so lamp and Tiger walks can be
combined. `speccalreset` starts a new list. Saved walks can also be
fitted later, outside the application:

```
python -m wavelength_calibration fit data/calibration_line_walks/linewalk_*.json
python -m wavelength_calibration fit <files> --curvature --triax-order 3 --apply
python -m wavelength_calibration fit <files> --curvature --triax-order 3 --plot
```

These save their report in the same place (`--report-directory` to change
it) and refuse `--apply` if a gate fails. `--fixed-dispersion` is the
equivalent of `fixeddispersion`.

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

In simulate mode, `speccal` runs against a simulated Ar-Hg lamp that emits
every line in the table at a brightness from its NIST intensity, weak
neighbours and second-order mercury included, clipped at the CCD's full
scale. The lamp has its own "true" calibration, ~2.7 nm away from the
shipped one, so you can practise the whole procedure (`speccal`,
`speccalfit`, `speccalapply`, `speccalzero`) and watch it find the offset.
The headless test suite runs these workflows, including a simulated loss of
120 TRIAX steps recovered by `speccalzero`, and `speccalapply` refusing a
simulated walk in a real session.

The simulator holding its own truth matters. The older simulated camera
placed the laser line using the software's own wavelength axis, so in
simulation every calibration looked perfect. The truth also has to be
physically complete, and as messy as the bench: the first line walk passed
every simulated test while it misidentified most lines on the bench,
because the simulated lamp only emitted the lines the software expected.
The unit tests now also give the simulated TRIAX a drive error that is not
a polynomial in steps (`periodic_triax_drive_error`), a cubic drive, a
strong line missing from the table, and a changed TRIAX scale, and check
that each is caught and explained.

### 3.7 Where the code lives

| File | Role |
|---|---|
| `wavelength_calibration/reference_lines.py` | the Ar-Hg line table (every NIST line that can reach the chip; confirmed references marked), external references |
| `wavelength_calibration/line_peaks.py` | peak finding and Gaussian fits, in pixels; collapsing a frame to a spectrum |
| `wavelength_calibration/line_identification.py` | identification by pattern over the whole walk, per-frame checks |
| `wavelength_calibration/line_walk.py` | the walk (hardware passed in as functions), saving, loading and re-identifying walk files |
| `wavelength_calibration/wavelength_axis_model.py` | the model, its exact inverse, the joint and two-stage fits |
| `wavelength_calibration/calibration_checks.py` | the gates: registry, residual decomposition, explanations |
| `wavelength_calibration/promotion.py` | re-identify, fit and check saved walks; the fit report; the master file |
| `wavelength_calibration/triax_zero.py` | the quick re-zero (`speccalzero`) |
| `wavelength_calibration/fit_plots.py` | the fit and residual plot (`plot` option) |
| `wavelength_calibration/provenance.py` | the software version recorded in each walk |
| `wavelength_calibration/simulated_line_lamp.py` | lamp + spectrometer simulator |
| `calibration.py` (`_load_wavelength_axis_model`) | loads the model at startup |
| `microscope.py` (`speccal*` commands) | connects the procedure to the TRIAX and PIXIS |
| `test_wavelength_calibration.py` | unit tests, including the replay of a bench walk (`test_fixtures/`) |

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

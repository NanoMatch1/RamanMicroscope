# Changelog

This file tracks functionally significant changes to the Raman microscope
control software. It does not track calibration data regeneration, log
churn, or other non-functional file noise — see git history for that.

## Known issues, to fix before the next merge into develop (found 2026-11-06 to 2026-11-10)

Open issues found by review and bench data. When an issue is fixed, its entry moves into the
dated section of the change that fixes it.

### PIXIS camera: still open

- The ADC runs at 2 MHz. The 100 kHz rate has lower read noise; worth comparing on the bench now
  that the ROI makes the readout time much smaller.
- The camera ROI is stored in `microscope_config.json`, which is tracked in git, although it
  belongs to one rig (where its slit image falls). The repository keeps other per-machine state
  out of git (`.gitignore`, MODERNIZATION.md 3.5); decide where it should live.

### Wavelength axis calibration: still open

- **The TRIAX drive is not a low-order polynomial in steps.** Over the full Ar-Hg walk the
  per-position TRIAX offsets sit 0.34 nm rms from a quadratic, 0.10 nm from a cubic and 0.05 nm
  from order 5 (2026-11-10). `triaxorder=N` and the TRIAX-shape gate (below) handle the smooth
  part; the remaining ~0.1 nm from one position to the next is the drive itself. A TRIAX position
  table interpolated between calibration positions would capture it (estimated 0.045 nm from
  the 2026-11-10 data; a walk with finer TRIAX steps would show whether interpolation holds).
- **`speccalfit triaxsigma=`** (added 2026-11-10) adds a TRIAX positioning error to each point
  to bring chi-squared down. It treats an error shared by every line in a frame as independent
  per line, which hides misidentified lines and model errors alike; the measured repeatability
  within a session is about 0.03 nm (3 steps), not the 25 steps in the example. It is kept for
  now, with a gate that says when it was used; decide whether to remove it.
- **Mercury sits ~0.05 nm off argon** in the same frames (first and second order alike), so
  mercury is identification-only. If argon and the Raman signal also light the slit
  differently, a lamp calibration carries a similar offset into Raman spectra: worth checking
  against a known Raman line once the axis is settled.

## PIXIS camera: ROI and binning, timeouts, gain; Tucsen leftovers removed (2026-11-11)

Branch `feature/pixis-camera-settings`. The Tucsen start-up applied binning, gain, the region of
interest (ROI), the set point and the fan; the PIXIS port kept only the set point (fixed
2026-11-06). These were found by review and on Riley's walks (the slit image at rows 567-818 of
frames that were full height although the software said 100 rows).

- **The ROI reaches the camera.** `camera.roi = (0, 0, 1024, 100)` existed only in software: the
  CCD read all 1024 rows (0.56 s per frame at 2 MHz) and every saved point was a full 1024x1024
  frame. The ROI is now a `SpectralRoi` (`pixisspec/spectral_roi.py`): sensor rows, all columns,
  and how many rows are binned on the chip. It is set through pylablib's validated `set_roi`,
  read back, stored in `microscope_config.json`, and set again at start-up.
- **ROI by hand or automatically.** `roi <first> <last>`, or the live viewer's new **Use selection
  as ROI**, sets the rows by hand, as should be done before collecting data; `roi auto` / **Auto
  ROI** finds the slit image on a full-sensor frame (and reports its tilt), for alignment, when it
  moves. Data taken without a hand-set ROI is flagged in the log. `speccal` and `speccalzero`
  check the slit image first, record it with the walk, and set an automatic ROI if the ROI misses
  it.
- **Software or on-chip binning** (`roi binning software|onchip`, a box in the live viewer):
  every ROI row read out, or the rows summed on the CCD for the least read noise.
- **`setbin` bins rows only** (`setbin N|all`). It binned both axes, which shortened the spectrum
  while the wavelength axis stayed 1024 points long, and passed the factor on as a string.
- **Every saved file records the camera readout** (`metadata['camera']`): the ROI as chosen and
  as the camera reports it, binning, exposure, gain, ADC speed, sensor temperature and set point.
  Calibration walks record it too.
- **Frame timeouts follow the exposure.** They were fixed at 10, 50 or 100 s per frame depending
  on the caller, so a longer exposure timed out; a frame is now waited for at least its exposure
  plus 30 s. The software sets no upper limit on the exposure; one the camera clips is reported,
  and `caminfo` lists the camera's allowed range.
- **`setgain low|medium|high` works.** It failed with AttributeError (`set_image_and_gain` does
  not exist on `PIXISCamera`), so the gain stayed at the camera default (High).
- **The initial wavelength axis** used `np.arange(roi[0], roi[2])`, wrong once the ROI has a
  column offset.
- **The simulated camera honours the ROI and binning.** The simulated scene is the whole sensor
  with the slit image at row ~800 (tilt settable), and the simulated device cuts out and bins the
  ROI as the CCD does, so the tests see what the bench sees.
- **Removed (Tucsen leftovers; git history keeps them):** the commands `camspec` and `camimage`
  (they set `acquire_mode`, which nothing read), `checkfan` and `autotemp` (no-ops on the PIXIS);
  `SimulatedCamera` (2048x148) and the broken `get_simulated_hardware` /
  `inject_simulated_hardware` in `simulation.py`; `Microscope.camera_set_acquisition_time` (used
  `self.camera.cam`, which does not exist) and `start_camera_ui`; the fan, image-processing,
  denoise and resolution stubs and the debugging helpers that mirrored the Tucsen class.

## Wavelength axis calibration: lines identified by pattern, gate checks, quick re-zero (2026-11-11)

Branch `feature/robust-line-identification`. Re-identifying the 2026-11-10 Ar-Hg walks found that
72 of the 91 points in the afternoon fit were a different line from the one recorded, which is
why reduced chi-squared was in the thousands. The wrong ones were weak neighbours of the lines
the walk expected:

| recorded as | actually | apart |
|---|---|---|
| Ar 811.531 | Hg 404.656 in second order (809.31) | 2.2 nm |
| Ar 922.450 | Ar 919.464 | 3.0 nm |
| Ar 738.393 | Ar 737.212 | 1.2 nm |
| Ar 751.465 | Ar 750.387 | 1.1 nm |
| Ar 842.465 | Ar 840.821 | 1.6 nm |

What caused it, and what changed:

- **Identification depended on the calibration in use.** Each line's pixel was predicted from
  it and the nearest peak within 4 px taken. That calibration (the migrated, circular one) put
  lines 8-37 px from where they landed, by an amount that changed along the walk, so a weak
  neighbour was often nearer the prediction than the line. Now the lines are identified by
  pattern over the whole walk (`wavelength_calibration/line_identification.py`): every strong
  peak in a frame must match a listed line under one offset, the walk is matched as a whole,
  and each frame's lines must agree with one pixel -> wavelength map to 0.03 nm. A correct
  identification agrees to ~0.005 nm and a wrong one is ~1 nm off, so a misidentified line
  cannot pass quietly. The calibration in use only has to be within +/-12 nm.
- **The line table left out lines that are there.** It now holds every NIST line that can reach
  the chip during a walk (argon, mercury in first order, mercury from 300-515 nm in second
  order), for identification. Only confirmed argon lines are fitted: four more than before
  (703.025, 737.212, 919.464, 935.422), all checked against NIST and against the 2026-11-10
  frames. The table had Ar 738.393; NIST gives 738.398. Mercury is identification-only (it
  sits ~0.05 nm off the argon lines on this instrument).
- **Repeated walks repeated the mistake**, so they looked consistent. They are now compared
  after correct identification (the walk-agreement gate).
- **Line-centre uncertainties were 10-1000x too small** for bright lines (background noise
  only). Each measurement now carries a floor of 0.05 px.
- **Walks did not record their conditions.** Walk files (format 2) now record the software
  version, simulate mode, exposure, frames averaged, ROI, sensor temperature and set point, the
  TRIAX position before the walk, and per frame the time, sensor temperature and the rows the
  spectrum came from. The row band is fixed by the first frame, so a tilted slit image cannot
  move lines between frames.
- **The walk only acquires;** identification runs afterwards, and `speccalfit` re-identifies from
  the saved spectra, so earlier walks get the new method and table.
- **The fit is two-stage** when frames have two or more lines: the CCD terms with a free offset
  per frame, then the TRIAX polynomial through the frame offsets. A TRIAX error the polynomial
  cannot follow no longer bends the CCD axis (in a simulated walk with a 0.15 nm drive error,
  the joint fit's CCD axis was 0.11 nm off; the two-stage fit's, 0.001 nm). Several walks get
  one zero each and share the shape; the latest walk sets the stored zero. `triaxorder=N` sets
  the TRIAX polynomial order.
- **Gate checks** (`wavelength_calibration/calibration_checks.py`) run with every fit: PASS,
  WARN or FAIL, each with its evidence, likely causes and what to try. `speccalapply` (and
  `python -m wavelength_calibration fit --apply`) refuses on any FAIL. They cover simulated or
  undocumented walks, camera conditions, an ambiguous identification, unidentified frames,
  unexplained peaks (with their wavelengths), the CCD axis within frames, per-line bias, the
  TRIAX shape (with the polynomial order the data supports), walk agreement (a moved zero, a
  drifting walk), coverage, saturation, fit statistics and the change from the calibration in
  use. The fit report holds them all, each walk's frame-by-frame identification and every
  residual.
- **`speccalzero`: quick re-zero after the TRIAX step count moves** (restart, lost steps). It
  revisits three of the calibration walk's positions, measures the shift in steps against the
  TRIAX position table the fit now stores, and if the gates pass stores it as the model's new
  `triax_step_offset`. If the frames disagree, the shape changed too and the report says to run
  the full calibration. `speccalzero check` only reports.
- **The simulator emits every listed line** at a brightness from its NIST intensity (weak
  neighbours and second-order mercury included), and can add a TRIAX drive error and shift the
  TRIAX counter, so the tests now meet the bench's difficulties. A replay test runs one of
  Riley's 2026-11-10 walks (`test_fixtures/`) and checks the misidentified peaks get their real
  names.
- **Fit plot: `speccalfit ... plot`** (also `speccalapply`, and `--plot` on the command line)
  saves a PNG next to the report: the TRIAX map with the fitted polynomial, the TRIAX residual
  frame by frame, the CCD-axis residual against pixel, and each line's residual. Riley had been
  plotting the residuals by hand in a spreadsheet to see them.
- **`speccal arhg samples=N`** sets how many places on the chip each line is seen at (default
  6). A denser walk shows how the TRIAX behaves between the usual positions.
- **Fixed: false peaks 2-3 px from bright lines** (Riley's 2026-11-11 walks). On broad lines, a
  bump on a line's wing was fitted in a 3 px window and the Gaussian climbed the bright line's
  flank to the window edge. Those false peaks counted as unexplained, failed frames, and in one
  frame at the chip edge one was taken for Ar 811.531 three pixels from the real line, failing
  the CCD-axis gate. A fit that runs more than 1.5 px from its starting peak is now dropped.
- **Fixed: the last frames of a walk were not identified** when the calibration in use bent away
  from the walk's straight trend there (0.5-1.7 nm on 2026-11-11), so the fit stopped short of the
  walk's end and extrapolated beyond it. Such frames are now identified from their neighbouring
  frames. A model also records the TRIAX range it was fitted over
  (`calibrated_triax_drive_steps`), the coverage gate warns when frames at a walk's ends go
  unidentified, and the application warns when the TRIAX is outside the fitted range. A
  calibration applied on 2026-11-11 (fitted before this fix) is off by up to 1.7 nm above ~117000
  steps; refit and re-apply it.
- **Walk metadata:** the camera's `roi` was recorded from a software attribute that start-up
  never sends to the camera, so it read `[0, 0, 1024, 100]` while the frames were full height.
  It is now recorded as `roi_setting_in_software`, and each frame records the shape the camera
  actually returned (`frame_shape`).

On the 2026-11-10 data, re-identified: the CCD axis agrees to 0.007 nm within frames, the walks
repeat to ~0.03 nm (3 TRIAX steps) apart from a first walk that drifted by up to 0.19 nm at its
start, and the TRIAX needs a cubic in steps over the full walk (see "still open" above).

## `speccalexport`: observed vs expected wavelength CSV (2026-11-10)

New command `speccalexport [files]` writes `spectral_calibration_scatter_<time>.csv` to
`data/calibration_fit_reports/` for the session's line walks (or the given walk JSONs; newest saved walk if
none). One row per line observation: `expected_nm` (lamp line), `observed_nm` (calibration in use applied to
the fitted pixel and TRIAX position), `error_nm`, uncertainties. For TRIAX repeatability trials, the spread of
`observed_nm` per `line_name` is the repeatability. Code: `wavelength_calibration/scatter_export.py`.

Also in this change: the headless suite no longer writes its simulated walks into the real
`data/calibration_line_walks/` folder (two had ended up among the 2026-11-10 bench walks); the
tests now redirect `line_walk_directory` to a temporary directory.

## PIXIS camera: acquire on demand, run only for live view (2026-11-06)

Branch `feature/pixis-acquire-on-demand`. The camera streamed from start-up
(pylablib "sequence" mode, free-running into a ring buffer) and `grab_frame`
returned the newest frame already in the buffer. After a move that frame had
been exposed before or during the move: on the lab PC at 0.5 s exposure,
5 of 5 grabs after a pause returned a frame exposed 1.0-1.8 s before the
request (`tools/pixis_frame_freshness_check.py`, judged by exposure time
stamps). Riley's line walks of 2026-11-04 show it as lines sitting at the
previous TRIAX position.

- **Acquire** (`grab_frame`, `RealHardware.acquire_frames`) is the default for
  everything that records data: an acquisition starts at the request, its
  first frames are read, and it is stopped while still running, so every frame
  is exposed after the request. The CCD is idle between acquisitions. Cost on
  the lab PC at full-chip readout: ~0.95 s per frame beyond the exposure
  (0.33 s start and clean, 0.56 s readout).
- **Run** (`run`, `start_continuous_acquisition`) keeps the free-running
  stream for live viewing during alignment (`grab_streamed_frame`). Any
  acquisition, exposure change or scan stops it first. Exposure, ROI and
  binning changes restart the stream only if it was running.
- pylablib's own `grab()`/`snap()` are not used: with pylablib 1.4.5 their
  `stop_acquisition()` can raise `PicamError_AcquisitionNotInProgress` after a
  snap has finished by itself (once in two runs on the lab PC).
- Frame averaging (`n_frames`) is a true mean (`acqcontrol.average_frames`);
  it was `(average + new) / 2`, which weighted the last frame 1/2 and the
  first 1/2^(n-1). The live view averages the same way.
- Sensor set point -50 °C (`RealHardware.SENSOR_TEMPERATURE_SET_POINT_C`), was
  -20 °C, the Tucsen's set point carried over in the port. This PIXIS reaches
  about -43 °C (vacuum no longer good enough for the specified -70 °C), so the
  cooler now runs flat out with status "Unlocked": roughly ten times less dark
  current than at -20 °C. The set point is committed to the camera when set;
  before, Picam held it until the next acquisition setup, so even -20 °C did
  not reach the camera at start-up. A set point the camera clips is logged.
- `grab_frame_safe` takes a frame once the sensor is at or below -30 °C
  (`SENSOR_TEMPERATURE_LIMIT_C`), which only catches a camera still cooling
  after power-on or one whose cooling has failed, and gives up after
  `temperature_wait_timeout_s` (default 10 min) with an error and no frame,
  instead of waiting forever. The discard-if-warmer-after check, needed for
  the Tucsen's temperature swings, is gone.
- Simulate mode runs `RealHardware` itself on `SimulatedPicamDevice`, a
  pylablib `PicamCamera` stand-in with a free-running CCD thread
  (`pixisspec/simulated_picam_device.py`); the simulated scene (laser line,
  or the line walk's lamp via `camera.simulated_scene.override_scene`) is
  `pixisspec/simulated_microscope_scene.py`. `SimulatedHardware` is removed.
- `Triax.go_to_steps`: the "coms anomaly" branch now waits for the move to
  finish instead of reporting success at once.
- New suite `test_pixis_camera.py`.

## Wavelength axis calibration: first bench walk fixes (2026-11-04)

The first real Ar-Hg walk gave a small rms but a reduced chi-squared above
5000, and matched some lines the lamp doesn't show.

- `WavelengthAxisModel` gains `nm_per_pixel_change_per_triax_step` and
  `dispersion_reference_triax_steps`: the dispersion falls as the grating
  turns (cos of the diffraction angle). A single nm_per_pixel left ~0.15 nm
  of error at the chip edges over 690-930 nm. `fit_wavelength_axis(...,
  fit_dispersion_change_with_triax=True)`; `speccalfit`/`speccalapply` and
  the command-line fit use it by default (`fixeddispersion` /
  `--fixed-dispersion` to turn it off). Master files without the new keys
  load with a fixed dispersion, as before.
- `CalibrationService.generate_wavelength_axis` takes the TRIAX steps, not
  the TRIAX wavelength, since the dispersion depends on them.
- Lamp catalogue `ARGON_MERCURY_LAMP_LINES`: the lines this lamp shows on
  this instrument. Mercury in orders 1-3 and Ar 710.748 (not seen) removed;
  the weak line at 871.6 nm (probably Hg 435.833, second order) is kept for
  identification only.
- Line walk files keep each position's spectrum (`position_records[].spectrum`).
- Every fit writes a report to `data/calibration_fit_reports/`: walks used,
  fitted terms, every residual, the model, and APPLIED/NOT APPLIED. An
  applied model names its report in metadata `fit_report`.
- `speccalfit`/`speccalapply` take any of `curvature`, `triaxquadratic`
  (quadratic TRIAX wavelength: the drive turns the grating angle, and
  wavelength goes as its sine), `fixeddispersion`, and refuse unknown
  options. The CLI has `--triax-quadratic`. A physical model of the TRIAX
  needs all three terms for a 690-930 nm walk:
  `speccalfit curvature triaxquadratic`.
- The simulated truth includes the dispersion change; new tests check
  that a fixed-dispersion fit is caught, and that a sin(angle) drive needs
  the full model (29 unit tests).

## Wavelength axis calibration: Ar-Hg lamp (2026-11-03, later)

The calibration lamp turned out to be argon-mercury, not mercury only.

- `reference_lines.argon_mercury_lamp_lines`: the lamp's labelled argon
  lines (label values), strong unlisted argon lines (NIST), mercury in
  orders 1-3, and the unresolved 772.376/772.421 pair flagged as unusable.
- `LineWalk` takes the full catalogue (`catalogue_lines`, renamed from
  `reference_lines`) and uses a line only when no other line is predicted
  within 8 px, the peak and prediction are mutual nearest neighbours, and
  the peak isn't saturated. The fit window shrinks to keep neighbours out.
  The pattern-match shift uses a 3 px tolerance.
- Planning slides the chip across the line range (6 samples per line, ~25
  positions for Ar-Hg) instead of targeting each line separately.
- `collapse_image_to_spectrum(saturation_level=...)` marks columns with a
  clipped pixel; `speccal` passes 65000 counts.
- `speccal` defaults to `arhg` (690-930 nm); `speccal hg` is gone, since the
  lamp's argon lines would confuse a mercury-only catalogue.
- Simulated lamp: per-line brightness, clipped at full scale.
- Tests: 26 wavelength-calibration unit tests (Ar-Hg recovery with uneven
  lines, saturated-line skip, catalogue, saturation marking).

## Wavelength axis calibration rebuilt (2026-11-03)

The TRIAX + PIXIS wavelength axis is the reference for every wavelength the
instrument reports. After the Tucsen -> PIXIS swap its pixel calibration was
refitted with `tools/Calibrationgenerator.py`, whose inputs were themselves
computed through the calibration being fitted, so it could only reproduce
the coefficients it started from. The slope survived (it scales exactly
with pixel pitch); the offset was never measured. Full account:
`docs/calibration.md` section 2.

### Added

- `wavelength_calibration/` package: the model
  `wavelength(pixel, triax_steps)` with an exact computed inverse; peak
  fitting in pixels; a line walk (TRIAX steps a known line across the
  chip, approaching from one direction); a weighted fit that refuses
  degenerate data; promotion to the master file with backup; a
  `python -m wavelength_calibration fit` command line. References: mercury
  lines in second order, or an externally measured line (Tiger on the
  spare spectrometer).
- Commands `speccal`, `speccalfit`, `speccalapply`, `speccalreset`.
- `Triax.go_to_steps()` (absolute move), factored out of `go_to_wavelength`.
- Simulated PIXIS `simulated_scene` hook. Simulate mode images a mercury
  lamp whose true calibration is independent of the one under test.
- `docs/calibration.md`; `test_wavelength_calibration.py` (22 tests) plus 4
  headless workflow tests; the new suite is in CI.

### Changed

- Master calibration: `camera_calibrations` and `triax_calibrations`
  replaced by one `wavelength_axis` group, same values
  (`tools/migrations/`), flagged unverified until a line walk is applied.
  `triax_to_wl`/`wl_to_triax` remain as `Calibration` attributes, now exact
  inverses of each other.
- `Calibration.generate_wavelength_axis` uses unit pixel spacing. The old
  `np.linspace(..., endpoint=True)` stretched the axis by 1/1023: up to
  0.08 nm at the far edge.
- `[POST-FIT]` log: "Centre pixel (512)" and "Peak pixel" are now real CCD
  columns (they were computed through the pixel calibration).
- `Triax.go_to_wavelength` (`st`) puts the requested wavelength on CCD
  pixel `spectrometer_target_pixel` (`microscope_config.json`, default 100)
  using the wavelength axis model. It used to stop a fixed 1910 steps short,
  which parked the requested wavelength at pixel ~274 on the PIXIS and wasted
  Stokes range.

### Fixed

- `Calibration.generate_master_calibration` / `generate_calibrations`:
  `if` -> `elif`, so a 7-coefficient poly+sine entry is no longer
  overwritten as a plain polynomial (latent; none exist yet).

### Deprecated

- `tools/Calibrationgenerator.py` marked non-functional (circular inputs, and
  it targets the removed `camera_calibrations` group). Kept for reference.

### Known consequences

- `calibration_shift_run_me.py` and `calibration_manual.py` look for the
  old `triax_calibrations` group and no longer find it. Both are offline
  scripts due to be archived in the calibration clean-up.

## Simulation repair and test harness (2026-08-20)

Follow-up to the migration commits below. Simulate mode did not start at
all; fixed that and added the missing test coverage. All fixes verified by
reinstating each bug and confirming the corresponding test fails.

### Fixed

- `instruments/spectrometers/triax.py`: the simulate branch of
  `_send_command_to_spectrometer()` called `self.spectrometer.query()` —
  the **pyvisa** API left behind by the GPIB implementation.
  `SimulatedTriaxSerial` mirrors **pyserial** (`write`/`read`), so every
  simulated read raised `AttributeError`. Because `Triax.initialise()`
  reads the position, this aborted startup entirely: simulate mode was
  completely unusable. Same root cause as the dead `_flush_read_buffer`
  removed in `f494577`.
- `instruments_old.py` `report_status()`: passed `{all_motors}` — a set
  literal wrapping the motor dict — to `identify_microscope_mode()`,
  raising `TypeError: unhashable type: 'dict'` on every `report` command
  that recalculated state.
- `instruments_old.py` `camera_info()`: called `self.camera.camera_info()`,
  which no camera class has ever implemented (the retired Tucsen class
  lacked it too, so `caminfo` was already broken before the migration).
  Now calls `get_camera_info()`, which `PIXISCamera` does provide.
- `instruments_old.py` `detect_microscope_mode()`: prompted via `input()`
  when the mode motor was not at exactly ±50000. In simulation the motor
  starts elsewhere, so this always prompted — during `initialise()`,
  making any headless or automated run hang on stdin. Now defaults to
  `ramanmode` when simulating; real-hardware behaviour is unchanged, since
  there the prompt is correct (the software genuinely cannot know the
  mode).
- `simulation.py`: `RAMAN_MODE_STEPS` was commented out but still
  referenced by `_raman_mode()`/`_image_mode()`, so both raised
  `AttributeError`. Restored. **Note:** its magnitude (100000) disagrees
  with `microscope_config.json` (`mode: 100000`) versus
  `detect_microscope_mode()`'s ±50000 test — only the sign is currently
  relied upon. Worth reconciling against the firmware.
- `simulation.py`: added the public `send_command()` that
  `SimulatedArduinoSerial`'s own docstring already documented but which
  did not exist, so tests no longer reach into `_parse_command()`.

### Testing

- **`test_headless_simulation.py` (new, 20 tests).** Full-workflow test
  driving the application through `Interface._command_handler` exactly as
  a CLI user would — startup, command registry, laser tuning and homing,
  spectrometer reads/moves, camera acquisition, microscope orchestration.
  Runs standalone (`python test_headless_simulation.py`) or under pytest.
  It replaces stdin with an empty stream so any prompt reached during an
  automated run fails fast instead of hanging. Includes explicit
  regression guards for each bug above. It snapshots and restores
  `tiger_step_position.json` so running the suite does not leave the
  laser's persisted position holding a simulated value.
- **`test_controller_simulated.py` (repaired, 9 tests).** Was importing
  `simulated_controller`, a module that does not exist, so the suite had
  been uncollectable — these failures predate the Tiger work. Repointed
  at `simulation.SimulatedArduinoSerial` (the class actually used at
  runtime), corrected the expected line ending to the protocol's CRLF,
  and fixed the `m...m` envelope spacing (`'m gsh on m'` → `'mgsh onm'`;
  the parser partitions on the first space, so the padded form yielded an
  empty command token). Mode-switch test now asserts a round trip rather
  than a magic step count.
- Total: **29 passing** (9 unit + 20 workflow).

### Known issues added

10. **`calibration/tiger_step_position.json` is tracked in git but is
    per-machine runtime hardware state**, exactly analogous to
    `instrument_state.json`, which is already gitignored. Pulling a
    committed value onto the lab machine would tell `TigerLaser` the
    piezomotor is somewhere it physically is not, making the next
    relative move wrong. Recommend `git rm --cached` + gitignore in the
    cleanup pass; the lab machine would keep its local copy.
11. **`interface_run_me.py` has `simulate = True` hard-coded** at the
    bottom, overriding the platform detection above it. Deliberately
    added for local testing and left uncommitted, but it must not reach
    the lab machine: it would run the microscope fully simulated with no
    hardware moving. A `--simulate` command-line flag would be a safer
    mechanism.
12. **`simulation.py:SimulatedArduinoController` is dead code.** The
    runtime path uses `SimulatedArduinoSerial`; this second class is
    unused, implements an older non-envelope protocol, and its
    `__init__` never creates the `laser_motors`/`monochromator_motors`
    attributes its own methods reference. Deletion candidate.
13. **`Triax.go_to_position()` is misleadingly named** — it sends `F0`,
    a *relative* grating move, so `sg 105500` shifts by 105500 steps
    rather than moving to that position. The simulator faithfully
    reproduces this. Pre-existing, but worth renaming.

## [Unreleased] — Tsunami → Tiger laser migration (2026-08-20)

Untracked working-tree edits made in the Melbourne lab to connect a new
Tiger Ti:Sapphire laser in place of the retired Tsunami. Captured here
before the first commit of this work. Reviewed and summarised by Claude
at Samuel's request; not yet split into individual commits.

### Laser: Tsunami → Tiger

- Added `instruments/lasers/tiger_laser.py` (`TigerLaser`) — RS-232 control
  (COM17, 9600 baud) of the Tiger's 1DBuP piezomotor tuning controller.
  Unlike the Tsunami, the Tiger is **not** stepper-motor tuned: it has no
  remote on/off, no power control, and no shutter command. Those
  `Microscope`-facing methods (`turn_on`, `turn_off`, `set_power`,
  `cycle_shutter`, ...) are now no-op stubs that log a warning and return a
  safe default so the rest of the call chain doesn't break.
- Added `instruments/lasers/tiger_calibration.py` (`TigerCalibration`) —
  step↔wavelength conversion. Deliberately switched from a 39-point cubic
  spline (which had ~10 nm systematic error from Runge's-phenomenon
  oscillation between poorly-verified points) to **linear interpolation
  over 6 verified measurement points**, range 765.546–840.035 nm
  (steps 2453–5400). More points can be added as they're measured.
- `microscope_config.json`: `action_groups.laser_wavelength` emptied
  (was `{l1, l2, l3}` → Arduino motor IDs) and the corresponding `l1/l2/l3`
  entries removed from `ldr_scan_dict`. The laser no longer has
  Arduino-driven axes.
- `instruments_old.py` (`Microscope`): `go_to_laser_wavelength` now
  delegates directly to `TigerLaser.go_to_wavelength()` instead of
  computing stepper-motor target positions via
  `calibration_service.wl_to_steps()`. The `@apply_pseudocal_forwards`
  decorator (a stepper-motor pseudo-calibration correction) was removed
  from this path accordingly.
  - `current_laser_wavenumber`, `report_laser_wavelength`,
    `current_monochromator_wavenumber` are now hardcoded to return `0.0`
    ("disabled — tuned via piezomotor"). **See Known Issues.**
  - The old `calculate_laser_wavelength` (which actually computed
    *grating* wavelengths from motor steps — a pre-existing naming bug)
    was renamed to `calculate_grating_wavelength`. A new
    `calculate_laser_wavelength` was added that is a no-op for the Tiger.
  - `MotionControl.get_motor_positions` now returns `{}` immediately for
    an empty motor dict, and `_parse_motor_positions` now tolerates empty/
    malformed controller responses instead of raising — both needed
    because the laser motor group is now empty.
  - `live_laser_calibration` decorator gained detailed post-fit logging
    (TRIAX/centre-pixel/Tiger-estimate/live-cal wavelengths) and is now
    also applied to `go_to_wavelength_all`.
  - `live_calibration_laser`: entrance slit width during auto laser-line
    detection changed from 5 → 7.

### Spectrometer: TRIAX moved from GPIB to RS-232

Not part of the laser swap, but bundled into the same uncommitted diff —
**flagging separately since it changes physical connectivity of a
different instrument.**

- `instruments/spectrometers/triax.py`: dropped `pyvisa`/GPIB
  (`GPIB0::1::INSTR`) entirely in favour of raw RS-232 (COM16, 4800 baud).
  Added a from-scratch "intelligent mode" handshake
  (`_enter_intelligent_mode`, `_is_initialised`, `_run_initialisation`)
  matching the TRIAX serial protocol (byte 248 to enter intelligent mode,
  `H0` to probe init state, space-triggered autobaud/init sequence, up to
  120 s).
- `go_to_wavelength`: the artificial `steps_correction` fudge factor
  (pushes the laser line to a known pixel) changed from 200 → 1910 —
  consistent with the camera swap below, but a large jump worth
  double-checking physically.

### Camera: Tucsen → Princeton Instruments PIXIS

Also not part of the laser swap, also bundled into the same diff.

- Added `pixisspec/pixiscam.py` (`PIXISCamera`) and
  `pixisspec/pixis_hardware.py`, built via `pylablib` as a drop-in
  replacement for the old `TucsenCamera` (deleted, along with all of
  `instruments/cameras/`, including the Tucsen SDK DLLs).
  `PIXISCamera` has a class-level singleton guard (`_instance_active`).
- Sensor width changed 2048 → 1024 px. Propagated to
  `calibration.py:generate_wavelength_axis` (default `array_length`) and
  `data_viewer_run_me.py`'s placeholder array shape.
- Exposure time convention (seconds in, converted to ms internally) is
  explicitly documented and consistent between `pixiscam.py` and
  `pixis_hardware.py`.

### Bug fix worth calling out: acquisition_time unit mismatch

`acquisitioncontrol/acqcontrol.py`: `general_parameters['acquisition_time']`
default changed from `1000.0` to `1.0`, with a comment explaining the old
value was a leftover millisecond convention being passed to a
seconds-expecting `set_exposure_time`, causing a **1000× exposure
overrun**. This looks like a genuine, previously-live bug that the student
caught and fixed. See Known Issues for a related loose end.

### Known Issues / follow-ups (found during this review, not yet fixed)

1. **Missing dependency: `pylablib`.** `pixis_hardware.py` does
   `from pylablib.devices import PrincetonInstruments` at module level,
   and `pixiscam.py` imports it unconditionally, and `interface_run_me.py`
   imports `pixiscam` unconditionally. `pylablib` is not in
   `requirements.txt`. **A clean environment (`pip install -r
   requirements.txt`) cannot start the application at all, even in
   `simulate=True` mode.** Highest-priority fix.
2. **Laser/monochromator wavenumber reporting is silently zeroed.**
   `current_laser_wavenumber`, `report_laser_wavelength`,
   `current_monochromator_wavenumber` always return `0.0`. Concretely:
   - The GUI's laser-wavelength label (`pyqtGUI.py`) will always show
     "0.00 nm".
   - `Microscope.report_status()` logs `'laser wavenumber': 0.0` and
     `'monochromator wavenumber': 0.0` on every status report.
   - `Microscope.laser_safety_check()` compares
     `current_laser_wavenumber` against `current_monochromator_wavenumber`
     — with both pinned at 0.0 this condition is trivially always true.
     Currently **no code path calls `laser_safety_check()`**, so this is
     dormant rather than actively wrong, but it should either be wired up
     correctly (using `TigerLaser.get_estimated_wavelength()`) or removed.
3. **Stale local config will silently set a 100 s exposure.**
   `acquisitioncontrol/acquisition_config.json` (gitignored, machine-local)
   still has `"acquisition_time": 100.0` from before the ms→s fix above.
   On next GUI launch this loads as **100 seconds**, not the old 100 ms.
   Needs a manual reset/edit on the lab machine.
4. **Orphaned reference to removed import.**
   `triax.py:_flush_read_buffer` still references
   `pyvisa.errors.VisaIOError`, but `import pyvisa` was replaced with
   `import serial` elsewhere in the same file. Nothing currently calls
   this method (leftover from the GPIB implementation), so it's dead
   code rather than an active crash — candidate for deletion.
5. **`requirements.txt` gained `gpib-ctypes` and `PyVISA-py`** even though
   neither `triax.py` nor `tiger_laser.py` use PyVISA/GPIB anymore (both
   now use raw `pyserial`). Looks like leftover exploration debris from
   before the RS-232 rewrite.
6. **`PIXISCamera` singleton guard is only released reliably via
   `__del__`.** `close_camera()` does not clear `_instance_active`; the
   one call site that reconnects (`Interface.connect_to_camera`) works
   around this by manually resetting the private class attribute rather
   than the class managing its own lifecycle.
7. **Dead scaffolding in `instruments_old.py`.** A new `Instrument(ABC)`
   base class is now defined locally in `instruments_old.py` (the old
   `from instruments.instrument_base import Instrument` was removed),
   separate from `instruments.instrument_base.Instrument`
   (`InstrumentBase` in `interface_run_me.py`). `Microscope` extends the
   local one; `TigerLaser`/`Triax`/`PIXISCamera` extend the package one.
   Two new stub classes, `Camera` and `Spectrometer`, were also added at
   the bottom of `instruments_old.py` and are never instantiated anywhere.
8. **Docstring/implementation mismatch.** `TigerLaser`'s class docstring
   states the calibrated range is "765.546 – 847.876 nm (steps
   1500 – 5400)"; the actual `TigerCalibration` data caps out at
   840.035 nm / step 2453. The docstring predates the switch to the
   6-point verified dataset.
9. **`.gitignore` lost its `.venv/` entry.** No `.venv/` currently exists
   in the working tree, so this hasn't bitten yet, but it should probably
   be restored before the first commit.

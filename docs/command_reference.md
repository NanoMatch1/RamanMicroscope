# Command reference

_Generated from the command docstrings by `tools/build_command_reference.py`; do not edit by hand. Change the docstring and re-run the script._

_Built from git e0d3c95 on feature/calibration-repeat-and-docs, with uncommitted changes._

Type a command and its arguments at the prompt, separated by spaces, e.g. `st 800`. `help` prints the same text; `exit` closes the camera and quits.

## Application

### `triax`

```text
Switch from simulated to real TRIAX spectrometer.
```

### `camera`

```text
Switch from simulated to real PIXIS camera.

── CHANGED ───────────────────────────────────────────────────────────
Previously instantiated TucsenCamera. Now instantiates PIXISCamera.
The singleton guard on PIXISCamera means the old instance must be
fully shut down before a new one can be created.
── END CHANGE ────────────────────────────────────────────────────────
```

### `laser`

```text
Switch from simulated to real laser.
```

### `logger`

```text
Set the logging level for the CLI and GUI interfaces.
```

### `calcheck`

```text
Temporary diagnostic — prints laser calibration values.
```

### `gui`

```text
Launch the GUI interface for the microscope control.
```

### `help`

```text
List every command with its docstring (docs/command_reference.md has the same).
```

### `runfile`

```text
Run a file of commands in order, e.g. 'runfile data/runfiles/stage1_edge_walk.txt'.

Each line is one command exactly as it would be typed here; blank lines and lines
starting with '#' are skipped. The whole file is checked first and nothing runs if any
line is not a known command (or a motor label with a whole number of steps). Then:
- each jogged motor is waited for until it stops, so the next line (an 'acquire')
  never starts while a grating is still moving;
- the run stops at the first command that reports an error, and says which line;
- Ctrl+C stops the run after the current command, leaving the application running;
- every command, its time and its result go to a run log in data/runfile_logs/,
  written as the run goes, so a stopped run still has its record.
Typed commands are lower-cased, so the file name is too; on the lab PC (Windows) the
case of a path does not matter. `python -m filter_calibration plan` writes the run
files for the stage 1 cutoff-edge calibration, and `python -m filter_calibration fit`
analyses their run logs.
```

## Tiger Ti:Sapphire Laser

### `connectlaser`

```text
Open the RS-232 connection to the Tiger piezomotor controller.
```

### `disconnectlaser`

```text
Close the RS-232 connection.
```

### `reconnectlaser`

```text
Close and reopen the RS-232 connection.
```

### `gettemp`

```text
Return the controller temperature in °C (column 3 of status string).
Waits up to STATUS_TIMEOUT seconds for the next broadcast.
```

### `getpower`

**Not reachable as `getpower`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Return the diode current in Amps (column 4 of status string).
This is the closest available proxy for laser power on the Tiger.
Waits up to STATUS_TIMEOUT seconds for the next broadcast.

Updates self.current_power so SimulatedMicroscopeScene threshold checks
(current_power >= 3) remain meaningful. The simulated diode current
is set to 4.52 A so the simulated laser line renders correctly.
```

### `laserstatus`

**Not reachable as `laserstatus`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Return a status summary string.
Tiger has no remote on/off so status is always 'ON' once connected.
```

### `stepup`

```text
Move the piezomotor in the wavelength-increase direction.

Parameters
----------
steps : int or str
    Number of steps (1 – 999999).
```

### `stepdown`

```text
Move the piezomotor in the wavelength-decrease direction.

Parameters
----------
steps : int or str
    Number of steps (1 – 999999).
```

### `setamplitude`

```text
Set piezomotor step amplitude (400–1000, default 600).
Higher = faster rotation and larger steps.
Do not set below 400.
```

### `setwidth`

```text
Set piezomotor step width / prolongation in microseconds (default 0).
```

### `settimeoff`

```text
Set time between piezomotor steps in microseconds (default 1000).
```

### `resetpiezo`

```text
Restore piezomotor settings to factory defaults.
```

### `wavelength`

```text
Return the estimated wavelength based on the current step position
and the cubic spline calibration.
```

### `gotowavelength`

```text
Move the piezomotor to achieve the target wavelength.

Uses the cubic spline calibration to convert wavelength → steps,
then moves relative to the current step position.

Parameters
----------
target_nm : float or str
    Target wavelength in nm. Must be within the calibrated range
    (765.546 – 847.876 nm).

Returns
-------
bool
```

### `laserhome`

```text
Home the piezomotor by moving to STEP_MAX (5400 steps, 765.546 nm).

Home is defined as the position where the laser outputs its shortest
calibrated wavelength (765.546 nm). From this known reference point,
step counts are meaningful across sessions.

An extra 1000 steps are added to the physical move to guarantee the
motor reaches the hard stop regardless of any accumulated drift or
hysteresis. The step_offset is then reset to the exact STEP_MAX value
(not STEP_MAX + 1000) so the calibration remains correct.

After a successful home move, step_offset is reset to the exact home
value, clearing any accumulated counting errors.
```

### `laseron`

**Not reachable as `laseron`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Not available on Tiger — no remote on/off command.
Logs a warning and returns True (laser assumed always on when connected).
```

### `laseroff`

**Not reachable as `laseroff`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Not available on Tiger — no remote on/off command.
Logs a warning. Does NOT change self.status to avoid breaking
SimulatedMicroscopeScene laser line rendering.
```

### `setpower`

**Not reachable as `setpower`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Not available on Tiger — power is set by the pump laser hardware.
Logs a warning and returns False.
```

### `enable`

**Not reachable as `enable`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Not available on Tiger — no remote enable command.
Returns True so Microscope.enable_laser() does not raise.
```

### `warmup`

**Not reachable as `warmup`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Not available on Tiger — no warmup query command.
Returns 100 so Microscope warmup checks pass immediately.
```

### `cycleshutter`

**Not reachable as `cycleshutter`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Not available on Tiger — no remote shutter command.
Logs a warning and returns False.
```

## Microscope

### `nyi`

```text
Placeholder for commands that are not yet implemented.
```

### `threads`

```text
Lists all active threads in the current process.
Returns a list of thread names.
```

### `pscal`

```text
Toggle the pseudocalibration correction.
```

### `livecal`

```text
Toggle the live calibration of the laser wavelength.
```

### `debugmode`

```text
Toggle the debug mode. In debug mode, all commands and responses are logged.
```

### `wai`

```text
"Where am I": report every motor's position and the laser and grating wavelengths
calculated from them with the calibrations.
```

### `rg`

**Not reachable as `rg`**: the same name is registered earlier in the lookup order, and that one runs.

```text
Get the current position of the spectrometer in motor steps.
```

### `sl`

```text
Move the Tiger Ti:Sapphire laser to the specified wavelength
via the piezomotor calibration, e.g. 'sl 800' for 800 nm.

Parameters:
wavelength (float): Target wavelength in nm

Returns:
bool: True if successful, False otherwise
```

### `sm`

```text
Move the monochromator to the specified wavelength, e.g. 'sm 805', leaving the other
gratings where they are. Moving the detection closer to the laser line shows
low-frequency modes; moving it further away cuts stray light and Rayleigh scattering.

Parameters:
wavelength (float): Target wavelength in nm

Returns:
bool: True if successful, False otherwise
```

### `sg`

```text
Move all gratings (first and second tunable filters) to the specified wavelength.

Parameters:
wavelength (float): Target wavelength in nm

Returns:
bool: True if successful, False otherwise
```

### `sall`

```text
Move all components (laser, monochromator, and spectrometer) to the specified wavelength.

Parameters:
wavelength (float): Target wavelength in nm
shift (bool): If True, maintains the current Raman shift. If False, sets monochromator to same wavelength.
```

### `st`

```text
Moves the spectrometer to the specified wavelength.
```

### `referenceall`

```text
Reference the current system configuration to a known laser wavelength (in nm).
Provide the true laser wavelength from an external reference.

Parameters
----------
wavelength : float
    Known laser wavelength (in nm).
shift : bool, optional
    Whether to apply Raman shift correction. Default is True.
```

### `referencelaser`

```text
Reference the current laser motor configuration to a known laser wavelength (in nm).
Provide the true laser wavelength from an external reference.

Parameters
----------
wavelength : float
    Known laser wavelength (in nm).
shift : bool, optional
    Whether to apply Raman shift correction. Default is True.
```

### `referencegratings`

```text
Reference the current system configuration to a known laser wavelength (in nm).
Provide the true laser wavelength from an external reference.

Parameters
----------
wavelength : float
    Known laser wavelength (in nm).
shift : bool, optional
    Whether to apply Raman shift correction. Default is True.
```

### `referencemono`

```text
Reference the current monochromator motor configuration to a known laser wavelength (in nm).
Provide the true laser wavelength from an external reference.

Parameters
----------
wavelength : float
    Known laser wavelength (in nm).
shift : bool, optional
    Whether to apply Raman shift correction. Default is True.
```

### `referencetriax`

```text
Used to reference the current motor position to the laser wavelength, as defined by the current calibration. Measure a spectrum on the TRIAX and enter the stepper motor position and pixel count of the peak wavelength here. In the future, this will be automated with a peak detection algorithm.
```

### `invertcal`

```text
Inverts the calibration for the laser and monochromator motors.
```

### `allmotors`

```text
Get the current positions of all motors in the motor_map
```

### `ramanmode`

```text
Set the acquisition mode to Raman mode.
```

### `imagemode`

```text
Set the acquisition mode to image mode.
```

### `wavelengthaxis`

_No docstring yet._

### `report`

```text
Prints the current status of the system. If initialise is True, the function will recalculate all parameters. If False, it will use the current values obtained from the initialisation.
```

### `writemotors`

```text
Writes the current motor positions to a file for a string entered by the user. Optionally, a dictionary of motor names to positions can be passed.
```

### `rldr`

```text
Reads the light-dependent resistor value from the microscope. Used to detect laser light in autocalibrations.
```

### `speccal`

```text
Walk known lines across the CCD with the TRIAX; save every spectrum.
Saved to data/calibration_line_walks/.
speccal / speccal arhg        Ar-Hg lamp lighting the TRIAX entrance slit (lines 696-935 nm)
speccal external 785.12 0.2   one line measured on another instrument (the Tiger on the
                              spare spectrometer): its wavelength and uncertainty in nm
speccal arhg samples=12       a denser walk: each line seen at ~12 places on the chip
                              instead of 6 (twice the positions and time)
speccal arhg repeat=3         three walks in a row, unattended (options combine:
                              'speccal arhg samples=24 repeat=3')
The lines are identified from all the spectra at once and the result is logged;
'speccalfit' re-identifies, fits and runs the gate checks. Keep the brightest lines below
saturation (65000 counts).
Repeated walks measure how well the TRIAX returns to a position: every walk is planned
from the calibration in use, so all of them visit the same TRIAX steps, each approached
from below. 'speccalfit' then fits them together; its 'walk agreement' gate says how
closely they agree and its report tabulates each walk's offset at each TRIAX position.
Do not run 'speccalapply' between walks that are to be compared. If one walk fails, the
walks saved before it are kept and the rest are not started.
Returns the saved walk's path, or a list of paths for repeat=N.
```

### `speccalfit`

```text
Fit this session's walks, run the gate checks, report. The master file is not changed.
speccalfit                     dispersion changing with the TRIAX position (the default)
speccalfit curvature           also fit the dispersion curvature across the chip
speccalfit triaxquadratic      TRIAX wavelength quadratic in steps; triaxorder=N for order N
                               (the TRIAX-shape gate suggests one)
speccalfit curvature triaxorder=3   recommended for the full Ar-Hg walk (2026-11-10 data)
speccalfit fixeddispersion     one nm_per_pixel for every TRIAX position (short walks only)
speccalfit triaxsigma=25       add a 1-sigma TRIAX error (steps) to every point; chi^2 then
                               no longer tests the fit
speccalfit curvature triaxorder=3 noplots   skip the plot (for headless runs)
The walks are re-identified from their spectra. The report, with every gate's verdict and
advice, is saved to data/calibration_fit_reports/, with a plot of the fit and its
residuals beside it (a PNG of the same name) unless noplots is given.
```

### `speccalexport`

```text
Export observed vs expected wavelength of the line walks to a CSV (e.g. after a TRIAX repeatability trial).
speccalexport            this session's walks (or the newest saved walk if none this session)
speccalexport <files>    the given line walk JSON files
Observed = wavelength the calibration in use gives the fitted line pixel at its TRIAX position; expected = lamp
line wavelength. Saved to data/calibration_fit_reports/ as spectral_calibration_scatter_<time>.csv.
```

### `speccalapply`

```text
Fit this session's walks and, if no gate check fails, write the master calibration.
Takes the same options as speccalfit (including noplots). The master file is backed up
first; the report and plot are saved to data/calibration_fit_reports/ either way.
```

### `speccalreset`

```text
Forget this session's line walks (the files stay on disk).
```

### `speccalzero`

```text
Quick re-zero after the TRIAX step count moved (restart, lost steps): about a minute.
speccalzero          measure the step shift and, if every gate check passes, store it in
                     the calibration in use
speccalzero check    measure and report only (a daily check)
The shape of the calibration is kept; only its TRIAX step offset changes. If the frames
disagree, more than the zero has changed and the report says to run the full calibration
(speccal, speccalfit, speccalapply).
```

### `autocal`

_No docstring yet._

### `loadconfig`

_No docstring yet._

### `readenterslit`

```text
Reads the current entrance slit width of the spectrometer.
```

### `x`

```text
Moves the microcsope sample stage in the X direction, by travel distance in micrometers. Note no backlash compensation is applied.
```

### `y`

```text
Moves the microcsope sample stage in the Y direction, by travel distance in micrometers. Note no backlash compensation is applied.
```

### `z`

```text
Moves the microcsope sample stage in the Z direction, by travel distance in micrometers. Note no backlash compensation is applied.
```

### `focus`

```text
Enters the mode for incrementally adjusting the microscope focus at the sample.
```

### `stagepos`

```text
Get the current stage positions in microns. Returns a dictionary of stage positions.
```

### `stagehome`

```text
Sets the current stage position as the home position.
```

### `setstart`

_No docstring yet._

### `setstop`

_No docstring yet._

### `scanres`

```text
Set the scan resolution in microns.
```

### `scanmode`

```text
Toggle between linescan and map in acquisition control
```

### `acquirescan`

```text
CLI command to acquire a scan.
```

### `laserpos`

```text
Get the current positions of the laser motors.
```

### `monopos`

```text
Get the current positions of the grating motors.
```

### `slsteps`

```text
Moves the laser motors to the specified positions in steps.

Parameters:
target_positions (dict): Dictionary of motor names to target positions {'l1': 1000, 'l2': 2000}
```

### `smsteps`

```text
Moves the monochromator motors to the specified positions in steps.

Parameters:
target_positions (dict): Dictionary of motor names to target positions {'g1': 1000, 'g2': 2000}
```

### `sgsteps`

```text
Moves the grating motors to the specified positions in steps.

Parameters:
target_positions (dict): Dictionary of motor names to target positions {'g1': 1000, 'g2': 2000}
```

### `recmot`

```text
Records the current motor positions to a file.
```

### `calhome`

_No docstring yet._

### `home`

```text
Home the specified motor, e.g. 'home l1'.

Parameters:
motor_label (str): The motor's label, e.g. 'l1', 'g2' (Microscope.motor_map).

Returns:
str: The response from the controller after homing the motor.
```

### `homeall`

```text
# Home all motors in the system.
```

### `homelaser`

```text
Home the laser motors.

Returns:
str: The response from the controller after homing the laser motors.
```

### `homemono`

```text
Home the monochromator motors.

Returns:
str: The response from the controller after homing the monochromator motors.
```

### `homegratings`

```text
Home the grating motors.

Returns:
str: The response from the controller after homing the grating motors.
```

### `testhoming`

```text
Test the reproducibility of the motor homing by moving to home and back in a cycle, n times.
```

### `polin`

```text
Moves the input polarizer to the specified angle.
```

### `polout`

```text
Moves the output polarizer (analyser) to the specified angle. Not implemented yet:
the command prints a notice and does nothing.
```

### `acqtime`

_No docstring yet._

### `filename`

```text
Set the file name for saved data, e.g. 'filename MoS2_flake3'.
```

### `ramanshift`

_No docstring yet._

### `runscan`

```text
Executes a scan based on the heirarchical acquisition scan built by the AcquisitionControl class.
```

### `cancel`

```text
Cancels the current scan.
```

### `mshut`

```text
Close the mechanical shutter.
```

### `mopen`

```text
Open the mechanical shutter.
```

### `nframe`

```text
Sets the number of frames to acquire.
```

### `acquire`

_No docstring yet._

### `acquirecustom`

_No docstring yet._

### `run`

```text
Starts continuous acquisition on the camera: the live view for alignment, plotted by
data_viewer_run_me.py. It shows the newest frame at once, so a frame can predate a move.
Acquisitions ('acquire', scans, calibrations) stop it and take their own frames, each
exposed after the request. 'stop' ends it.
```

### `stop`

```text
Stops continuous acquisition on the camera.
```

### `roi`

```text
Camera region of interest: which sensor rows make the spectrum, and their binning.
roi                     report the ROI on the camera
roi <first> <last>      read sensor rows first..last (both included), chosen by hand;
                        the live viewer's 'Use selection as ROI' does the same
roi auto [margin]       find the slit image on a full-sensor frame (light on) and read
                        its rows plus `margin` rows (default 3) each side
roi full                read the whole sensor
roi binning software    read every ROI row out (the default)
roi binning onchip      sum the ROI rows on the CCD: one read per column, least noise
The ROI is stored in microscope_config.json and set again at start-up. Before collecting
data, choose the rows by hand around the slit image and no wider.
```

### `setbin`

```text
On-chip binning of the ROI rows (columns are never binned):
setbin 1      no on-chip binning: every ROI row is read out (software binning)
setbin all    all ROI rows summed on the CCD (same as 'roi binning onchip')
setbin N      groups of N rows summed on the CCD
```

### `caminfo`

```text
Prints the camera information.
```

### `temp`

```text
Returns the camera temperature.
```

### `settemp`

_No docstring yet._

### `refresh`

```text
Refreshes the camera connection.
```

### `camclose`

```text
Closes the hardware camera connection. Allows connection via Mosaic UI.
```

### `camopen`

```text
Opens the hardware camera connection. 
```

### `setgain`

```text
ADC analogue gain: setgain low | medium | high. Higher gain gives more counts per
electron (less quantisation for weak signals) and saturates sooner.
```

### `setpower`

```text
Sets the laser power to the specified value.
```

### `getpower`

```text
Returns the current laser power.
```

### `laseron`

```text
Turns the laser on.
```

### `laseroff`

```text
Turns the laser off.
```

### `cycleshutter`

```text
Cycle the laser shutter. Not available on the Tiger, which has no remote shutter
control: the command only logs a warning.
```

### `laserstatus`

```text
Returns the current laser status.
```

### `enable`

```text
Enable the laser. Not available on the Tiger, which has no remote enable command:
the command only logs a warning.
```

### `warmup`

```text
Returns the current laser warmup status.
```

## TRIAX Spectrometer

### `get_spectrometer_position`, `rg`

```text
Get the current position of the spectrometer in motor steps.
```

### `ren`

```text
Read the current position of the entrance slit: 25-50 microns for standard operation.
```

### `rex`

```text
Read the current position of the exit slit.
```

### `men`

```text
Open or close the entrance slit by a relative amount, in micrometres.

A positive number opens the slit, a negative one closes it. The move is relative to
where the slit is now, not a target width: read the width first with `ren`.

Examples:
    men 450     open by 450 um (e.g. from 50 um to about 500 um)
    men -450    close by 450 um
```

### `mex`

```text
Move the exit slit to the specified position.
```

### `mg`

```text
Move the grating the specified number of steps.
```

### `initialise`

```text
Initialise the spectrometer.
```

### `specgrat1`

```text
Set the default gratin;'g for the spectrometer.
```

### `specgrat2`

```text
Set the other grating for the spectrometer.
```

## Motors (jogging)

### `<motor label> <steps>`

```text
Jog one motor by a number of steps from where it is (relative, either sign), e.g.
'g2 -40'. Type the motor's label and the steps; the labels are listed below. For
alignment and calibration, when a whole-instrument command (a wavelength) is too coarse.
The move goes straight to the controller: no backlash correction is applied.
```

| Group | Motor labels (controller id) |
|---|---|
| grating_wavelength | `g1` (3Z), `g2` (3A), `g3` (3X), `g4` (3Y) |
| monochromator_wavelength | `g3` (3X), `g4` (3Y) |
| polarization | `p_in` (4X), `p_out` (4Y) |
| triax | `triax` (triax) |
| stage_movement | `x` (2X), `y` (2Y), `z` (2Z), `mode` (2A) |

## How it works: PIXIS camera: live view, acquisitions, exposures

The PIXIS camera as the application uses it: live view, acquisitions, exposures and readout.

- Live view (`run`): the camera streams frames for alignment, shown by data_viewer_run_me.py.
  The newest frame is shown at once, so a frame can predate a move. `stop` ends it.
- Acquisitions (`acquire`, scans, calibrations) stop the live view and take their own frames,
  each exposed after the request.
- Exposures are not limited in the software: a frame is waited for its exposure plus 30 s
  (RealHardware.FRAME_TIMEOUT_MARGIN_S), so minutes per frame are fine. If the camera cannot
  take an exposure it says so, and `caminfo` lists its allowed range. For long exposures,
  consider several frames (`nframe`) rather than one: a cosmic ray then spoils one frame, not
  the whole point.
- The PIXIS has no shutter, so the sensor keeps collecting light while a frame is read out. At
  short exposures a frame holds noticeably more light than the exposure alone (an on-chip
  binned "10 ms" frame held 5.4 times the light of 10 ms, lab-notebook RAM-F3), and each line
  smears faintly along its column. Saved data records the camera's readout time
  (`readout_time_s` under `camera` in the metadata) so this can be allowed for.
- The cooler runs flat out: the set point (-50 C) is below what this sensor reaches (about
  -43 C), which gives the coldest sensor and the least dark current.

The rows read out and their binning are set by the ROI (pixisspec/spectral_roi.py).

## How it works: Camera region of interest and binning

Which CCD rows make the spectrum, and how they are binned.

The spectrograph images the entrance slit as a band of rows across the PIXIS (1024 x 1024);
the spectrum runs along the columns. Reading only the rows of that band (the region of
interest, ROI) cuts the readout time and the file size, and leaves out rows that hold only
dark current and read noise. Only the ROI rows are saved.

Setting the ROI:

- During alignment, `roi auto` (or Auto ROI in the live viewer) takes one frame of the whole
  sensor with the light on, finds the slit image (`find_slit_image`) and reads its rows plus 3
  each side. It also reports the slit image's tilt across the chip, in rows per 1000 columns,
  which should be close to zero once the camera is square to the spectrograph. `roi full`
  reads every row, to see where the light falls.
- Exposure for `roi auto`: about 1 s with the Ar/Hg lamp (0.3 s was the shortest that worked
  on the 2026-11-12 lamp frames, lab-notebook RAM-F3). The PIXIS has no shutter, so light keeps
  landing on the rows while they are shifted out to be read (about 0.5 s for the whole
  sensor). That smears every line along its column, the faint streaks above and below the
  lamp lines, and the smear does not shrink with the exposure. When the smear outweighs the
  slit image, `roi auto` says to lengthen the exposure instead of guessing the rows. With
  on-chip binning's short exposures, lengthen the exposure for the `roi auto` frame, then
  shorten it again.
- Before collecting data, choose the rows by hand: in the live viewer, drag over the slit
  image in the frame (or type Ymin/Ymax) and press Use selection as ROI; or
  `roi <first row> <last row>`. Take the rows where the slit image is bright and no wider, so
  no rows of pure noise are binned in. Data taken with an automatic or full-sensor ROI is
  flagged in the log.
- The ROI is stored in microscope_config.json and set again at start-up. Every saved file
  records the ROI and binning the camera reported, with the exposure, readout time, gain, ADC
  speed and sensor temperature (`metadata['camera']`). A lamp calibration (`speccal`,
  `speccalzero`) checks the slit image first and records it with the walk; if the ROI misses
  it, it sets an automatic ROI.

Two ways to combine the ROI rows into one spectrum (the box in the live viewer, or
`roi binning software|onchip`, or `setbin`):

- software binning (`rows_binned_on_chip = 1`): every ROI row is read out and saved, and the
  rows are combined afterwards. The frame still shows where the slit image sits, how it is
  tilted, the readout smear, and which rows a cosmic ray hit.
- on-chip binning (`rows_binned_on_chip = row count`): the CCD sums the rows' charge before
  the single read of each column. The frame is one row, so the slit image can no longer be
  checked from the data.

A value between the two bins that many rows per output row.

Which binning when: software while troubleshooting and aligning, because it shows what the
CCD sees; on-chip for acquisitions. Both read only the ROI rows; the difference is how many
pixels are digitised. Every read adds read noise (a fixed amount per read, from the output
amplifier and the ADC), and noises from separate reads add in quadrature, so summing N rows
read one by one gives sqrt(N) times the read noise of one read: about 12.6 times for a 158-row
ROI. On-chip binning adds the charge of the N rows together first and reads it once, so it
carries the read noise of one read. It also reads out faster: one row of 1024 pixels is
digitised instead of N (about 0.5 ms per row at 2 MHz), though shifting the rows down to the
readout register still takes its time (`readout_time_s` in the metadata gives the total).

The noise advantage matters while read noise dominates: weak signals and short exposures.
Binning does not reduce the shot noise of the signal or of the dark current (that charge is
summed either way), so in long exposures (minutes) the gain shrinks;
tools/pixis_dark_noise_check.py measures where that happens on this camera. The costs: bright
lines saturate sooner (the sum is clipped at the ADC full scale, 65535 counts: column 399 of
the Ar/Hg lamp did at "10 ms", RAM-F3), and cosmic rays cannot be seen or removed in a one-row
frame, so split long points into several frames (`nframe`).

This module is pure: no camera or GUI.

## How it works: Stage 1 edge (g1) calibration: run files and analysis

Command line for the stage 1 edge (g1) calibration, run from the repository root.

    python -m filter_calibration plan --exposure 15 --axis-exposure 15
        writes the four run files to data/runfiles/ (see run_files.py)
    python -m filter_calibration fit data/runfile_logs/stage1_*_20261201_*.txt
        analyses the session those run logs recorded (here, every stage 1 run of 2026-12-01):
        report, results.json and plots in data/filter_calibration_reports/stage1_edge_<time>/
    python -m filter_calibration fit <logs> --apply
        also writes the proposed g1 and g2 entries into the master calibration (backed up first),
        and refuses if a gate check fails

`fit` saves its plots unless --no-plots is given (for headless runs). It expands wildcards
itself (the Windows command prompt does not), and finds the frames under --data-directory
(default data/) by the names in the logs. Pass every run log of the session, and only that
session's (older runs have the same frame names): the walk gives the calibration, the axis
references correct it, and the single steps and the repeatability run are checked against it.
Re-running the command in a report gives the same result from the same files; results.json
records each file's SHA-256.

## Command names registered more than once

The CLI runs one method per name: the application's commands first, then the instruments' (where two instruments clash, the later one in attribute-name order), then the motor labels.

| Command | Registered by | Runs |
|---|---|---|
| `cycleshutter` | Tiger Ti:Sapphire Laser (`TigerLaser.cycle_shutter`); Microscope (`Microscope.cycle_laser_shutter`) | `Microscope.cycle_laser_shutter` |
| `enable` | Tiger Ti:Sapphire Laser (`TigerLaser.enable_laser`); Microscope (`Microscope.enable_laser`) | `Microscope.enable_laser` |
| `getpower` | Tiger Ti:Sapphire Laser (`TigerLaser.get_power`); Microscope (`Microscope.get_laser_power`) | `Microscope.get_laser_power` |
| `laseroff` | Tiger Ti:Sapphire Laser (`TigerLaser.turn_off`); Microscope (`Microscope.laser_off`) | `Microscope.laser_off` |
| `laseron` | Tiger Ti:Sapphire Laser (`TigerLaser.turn_on`); Microscope (`Microscope.laser_on`) | `Microscope.laser_on` |
| `laserstatus` | Tiger Ti:Sapphire Laser (`TigerLaser.get_status`); Microscope (`Microscope.get_laser_status`) | `Microscope.get_laser_status` |
| `rg` | Microscope (`Microscope.get_spectrometer_position`); TRIAX Spectrometer (`Triax.get_spectrometer_position`) | `Triax.get_spectrometer_position` |
| `setpower` | Tiger Ti:Sapphire Laser (`TigerLaser.set_power`); Microscope (`Microscope.set_laser_power`) | `Microscope.set_laser_power` |
| `triax` | Application (`Interface.connect_to_triax`); Motors (jogging) (`Interface.jog_motor`) | `Interface.connect_to_triax` |
| `warmup` | Tiger Ti:Sapphire Laser (`TigerLaser.get_warmup_status`); Microscope (`Microscope.get_warmup_status`) | `Microscope.get_warmup_status` |
| `x` | Microscope (`Microscope.move_x`); Motors (jogging) (`Interface.jog_motor`) | `Microscope.move_x` |
| `y` | Microscope (`Microscope.move_y`); Motors (jogging) (`Interface.jog_motor`) | `Microscope.move_y` |
| `z` | Microscope (`Microscope.move_z`); Motors (jogging) (`Interface.jog_motor`) | `Microscope.move_z` |

## Commands without a docstring

`acqtime`, `acquire`, `acquirecustom`, `autocal`, `calhome`, `loadconfig`, `ramanshift`, `setstart`, `setstop`, `settemp`, `wavelengthaxis`

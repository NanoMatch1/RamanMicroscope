# DRR Working Notes
## Microscope startup and initialisation

1. Boot the software by running the `interface_run_me.py` script. **ENSURE the power to the motors is OFF**.
2. Once provided a `Enter command` prompt, turn on the motor power at the controller switch.
3. Type `enable` to begin first phase of laser warmup
4. `homelaser` to home all laser motors
5. `homegratings` to home all grating motors
6. Use `sall` $\lambda$ to go to a specific wavelength. 
    - NOTE: A go-to command is required after homing any motor.
    - Homing motors brings them to the zero steps position. All motors at zero does not equate to any calibrated wavelength, so a go-to command is required to realign to a chosen wavelength.
7. If not yet done, open or cycle the shutter `cycleshutter` or `shutteron`
8. Confirm the laser is lasing at the design wavelength. At the design wavelength, the laser will make it to the pinhole and should pass through the rest of the microscope to the sample. 
- **Troubleshooting**: If the laser does not lase properly, or is weak, sometimes the l2 motor is not where it should be after homing (this is not common but can happen). Rehome just l2 with `home l2` and follow up with `sl` $\lambda$. If this does not fix it, manually jog the motor until lasing is restored. Find the motor position that centres the alignment on the lasing condition, then use `reference` $\lambda$ to reference this set of motor positions to this wavelength.
9. Ensure lasing at the sample (sulfur test).
10. Type `run` to initiate the continuous acquisition for focus and alignment. NOTE: The `data_viewer_run_me.py` should be running in a separate window. If not, go to the RamanMicroscope code folder and run this file by double clicking.
11. In the data viewer UI, ensure the ROI start and end are set to a logical range. Usually 100-2000 respectively. Toggle autoscale as required to view the spectrum and lock/normalise the intensity range. 
12. Check the camera ROI: the CCD rows that make the spectrum (see **Camera region of interest** below). The application sets the stored ROI at start-up and says so; if the slit image has moved (after any work on the camera or spectrograph), set it again before collecting data.
13. Upon running, the data viewer should update with live data each frame. The sulfur spectrum should be just barely visible at 1 second acquisition time if you're lucky. If not:
    1. Check the sample is in focus 
    2. **the motors may need to be jogged into alignment**

### Jogging motors:
After homing, sometimes the motors can be slightly off still. I believe this is a consequence of inaccuracy in the limit switch positions and the absolute positioning of the grating motor drivers. The fix is to massage the setup into its final alignment.

1. start with motor G1. You can place a target card in the cage system near the 45 degree vertical turn (just after the beamsplitters). The laser should pass dead centre through the target card. If not, use `g1 x` to move the motor x steps. Do this until it passes through the target card centre.
2. Remove the target card.
3. Next, work through the other motors by observing changes to the spectrum. 
    - g2, g3, g4
    - The intensity should reach a maximum within 1-3 steps of their current positions. Find the maximum value for the motor, then move on to the next.
    - Once all motors have reached their maximum intensities, you can cycle back and repeat once more.
    - Once you are satisfied with the intensities, reference this position (`reference` $\lambda$) and move on.

The microscope should now be aligned and calibrated, ready for scans.

# Running a Scan
The scanning controls are currently all managed with a separate UI. Type `gui` to load this UI.
Here you can select start and end positions and resolution for all scan dimensions: Stage motion, wavelength, and polarization. You can also edit filename and acquisition time.
Select settings as desired
Tick the box to "enable scan mode"
Click "start scan acquisition" to begin scanning acquisition.

The files are saved to a folder of the filename, inside the data directory of the main RamanMicroscope folder. These will be processed later by analysis scripting.

# Control Notes

The primary form of interaction with the microscope is via the command line interface. This will change over time to a Graphical User Interface, but the command line interface will always be accessible for debugging and convenience.

## How To Use Commands
All commands can be passed arguments in the form of characters separated by `<space>` keys. For instance, `sl` is the "go to laser wavelength command", and it requires a laser wavelength as a number for its argument. The command to move to 750 nm laser excitation is `sl 750`.

### Frequent Commands
- `wai`: "where am I" prints the current motor positions and calculates the laser and grating wavelengths using the calibrations
- `sl` $\lambda$: set laser wavelength to specified value (e.g. `sl 800` for 800 nm)
- `sg` $\lambda$: set wavelength on all gratings (microscope filter and double monochromator)
- `sm` $\lambda$: set wavelength on just the monochromator gratings. Useful for moving the detection closer to the laser line (for seeing low-frequency modes) or further from the laser line (to reduce stray light and rayleigh scattering signal)
- `st` $\lambda$: set TRIAX spectrometer wavelength
- `sall` $\lambda$: set all wavelengths (for changing the whole setup to a specific wavelength)

- `homelaser`: homes the three laser motors in sequence
- `homegratings`: homes all grating motors in sequence
- `home` $motorlabel$: homes the motor of $motorlabel$ (e.g. `home l1`)

- `reference` $\lambda$: reassigns the current motor positions to the wavelength of choice. Used when making minor adjustments to the alignment of the laser or gratings.

- `ren`: read entrance slit on the spectrometer. Should be between 25 and 50 microns for standard operation
- `men`: move entrance slit on the spectrometer.


- `run`: runs the camera in continuous acquisition mode. Data is plotted to the data_viewer_run_me.py
  This is the live view for alignment: it shows the newest frame at once, so a frame can predate a
  move. Acquisitions (`acquire`, scans, calibrations) stop it and take their own frames, each
  exposed after the request.
- `stop`: stops a continuous acquisition.
- `filename` $string$: sets the current filename ($string$) for saved data
- `gui`: brings up the GUI for preparing and performing multidimensional scan datasets

- `enable`: cycles through the startup sequences of the laser. Repeated calls to `enable` progress the startup sequence:
    1. Checks the warmup start and initiates diode warmup
    2. Enables the laser at non-lasing power (0.05 W) for second warmup.
    3. Turns the laser to 4.0 W - laser is fully on, but shutter is closed still
- `shutteron`: opens the laser shutter
- `shutteroff`: closes the shutter
- `cycleshutter`: closes then reopens the shutter. Useful for startup because the shutter sometimes doesn't open when it should

### Individual Motor Motion
Sometimes you need to jog the motors a small number of steps, for alignment or for calibration. This is done by typing the motor label and the number of steps you want to move (relative motion not absolute), either positive or negative direction.

- `l1` $x$: move laser motor 1 $x$ steps
- `l2` $x$: move laser motor 2 $x$ steps
- `l3` $x$: move laser motor 3 $x$ steps
- `g1` $x$: move grating motor 1 $x$ steps
- `g2` $x$: move grating motor 2 $x$ steps
- `g3` $x$: move grating motor 3 $x$ steps
- `g4` $x$: move grating motor 4 $x$ steps


## Adidtional Commands
Many of these commands are required for maintenance but some have calibration-breaking consequences (not permanent but annoying). Only use commands you are familiar with and know what the consequences are.

### 🔧 **System Control**

- `report`: Show current system status (pass `initialise=True` to refresh all parameters).
- `loadconfig`: Load system configuration.
- **`gui`: Launch GUI interface (if available).**
- `cancel`: Cancel current scan.
- `runscan`: Run scan using current acquisition parameters.
- `refresh`: Refresh camera connection.
- `closecamera`: Fully close camera interface (for external GUI takeover).
- `allocate`: Allocate buffer for camera acquisition
- `deallocate`: Deallocate camera buffer and stop acquisition.

---

### 🧭 **Motor Homing and Position**

- **`home(motor_label)`: Home specific motor, e.g., `'1X'`, `'2Y'`.**
- `homeall`: Home all motors.
- **`homelaser`: Home laser motors.**
- `homemono`: Home monochromator motors.
- **`homegratings`: Home grating motors.**
- `stagehome`: Set current XY(Z) stage position as home.
- `testhoming`: Cycle home movement to test reproducibility.

---

### 📍 **Motor Positioning (Steps)**

- `slsteps(target_dict)`: Move laser motors to target steps (e.g., `{'l1': 1000}`).
    
- `smsteps(target_dict)`: Move monochromator motors to target steps.
    
- `sgsteps(target_dict)`: Move grating motors to target steps.
    
- `allmotors`: Print current step positions of all motors.
    
- `laserpos`: Get laser motor positions.
    
- `monopos`: Get monochromator/grating motor positions.
    
- `rg`: Get current spectrometer motor step position.
    

---

### 🌈 **Wavelength-Based Motion**

- `sl(wavelength_nm)`: Move laser to specified wavelength.
    
- `sm(wavelength_nm)`: Move monochromator to specified wavelength.
    
- `sg(wavelength_nm)`: Move all gratings to specified wavelength.
    
- `st(wavelength_nm)`: Move spectrometer to specified wavelength.
    
- `sall(wavelength_nm, shift=True/False)`: Move all components; `shift=True` maintains Raman shift.
    

---

### 🧪 **Calibration & Referencing**

- `reference(wavelength_nm, shift=True)`: Reference system to known laser wavelength.
    
- `referencetriax(step_pos, pixel_pos)`: Reference spectrometer step to a CCD pixel (manual).

- `speccal` (Ar-Hg lamp) / `speccal external <nm> <uncertainty_nm>`: line walk to calibrate the TRIAX + CCD wavelength axis. `speccalfit [curvature] [triaxorder=N] [fixeddispersion]` re-identifies the lines, fits and runs the gate checks (`speccalfit curvature triaxorder=3` for the Ar-Hg walk), `speccalapply` (same options) writes the master calibration unless a gate fails, `speccalreset` clears the session. Both save a report with every gate's verdict and advice to `data/calibration_fit_reports/`. `speccalzero` re-measures the TRIAX zero in about a minute after a restart or lost steps (`speccalzero check` only reports). See [the calibration guide](calibration.md), section 3.
    
- `invertcal`: Invert calibration mappings (laser & monochromator).
    
- `recmot`: Save current motor positions.
    
- `writemotors(label, pos_dict=None)`: Write positions with optional manual override.
    
- `calhome`: (TBD)
    

---

### 📸 **Camera Control**

- `camera`: Connect to camera.
    
- `camclose`: Disconnect hardware interface.
    
- `caminfo`: Print camera info.
    
- `temp`: Get camera temperature.
    
- `roi`: Show the camera region of interest; `roi <first row> <last row>`, `roi auto`, `roi full`, `roi binning software|onchip` set it (below).
    
- `setbin N|all`: Bin N ROI rows on the chip (`1` = none, `all` = every ROI row). Columns are never binned.
    
- `setgain low|medium|high`: ADC analogue gain (more counts per electron at higher gain; saturates sooner).
    
- `acquire`: Acquire a single frame (if implemented).
    
- `run`: Start continuous acquisition (live view; stopped by any acquisition).
    
- `stop`: Stop continuous acquisition.
    
#### Camera region of interest (ROI)

The spectrograph images the entrance slit as a band of rows across the PIXIS; the spectrum runs along the columns. The ROI is the rows that are read out: only they are saved, the readout is faster, and rows that hold only dark current and read noise stay out of the spectrum.

- **During alignment**, `roi auto` (or **Auto ROI** in the live viewer) takes one frame of the whole sensor with the light on, finds the slit image and reads its rows plus 3 each side. It also reports the slit image's tilt across the chip, in rows per 1000 columns, which should be close to zero once the camera is square to the spectrograph. `roi full` reads every row, to see where the light falls.
- **Exposure for `roi auto`:** about 1 s with the Ar/Hg lamp (0.3 s is the shortest that worked on Riley's 2026-11-12 frames). The PIXIS has no shutter, so light keeps landing on the rows while they are shifted out to be read (about 0.5 s for the whole sensor). That smears every line along its column, the faint streaks above and below the lamp lines, and the smear does not shrink with the exposure. At short exposures the smear outweighs the slit image and `roi auto` says to lengthen the exposure instead of guessing the rows. It also works poorly with on-chip binning's short exposures: lengthen the exposure for the `roi auto` frame, then shorten it again.
- **Before collecting data**, choose the rows by hand: in the live viewer, drag over the slit image in the frame (or type Ymin/Ymax) and press **Use selection as ROI**; or `roi <first row> <last row>`. Take the rows where the slit image is bright and no wider, so no rows of pure noise are added in. Data taken with an automatic or full-sensor ROI is flagged in the log.
- **Binning** (the box in the live viewer, or `roi binning software|onchip`): *software* reads every ROI row out, so the frame still shows the slit image and cosmic rays; *on-chip* sums the rows on the CCD before the single read of each column, which gives the least read noise for weak signals but a one-row frame, and bright lines saturate sooner (the sum is clipped at 65535 counts).
- The ROI is stored in `microscope_config.json` and set again at start-up. Every saved file records the ROI and binning the camera reported, with the exposure, gain, ADC speed and sensor temperature (`metadata['camera']`).
- A lamp calibration (`speccal`, `speccalzero`) checks the slit image first and records it with the walk; if the ROI misses it, it sets an automatic ROI.

Exposures are not limited in the software: a frame is waited for its exposure plus 30 s, so minutes per frame are fine. If the camera cannot take an exposure it says so, and `caminfo` lists its allowed range. For long exposures, consider several frames (`nframe`) rather than one: a cosmic ray then spoils one frame, not the whole point.

---

### 🌀 **Stage Control**

- `x(um)`, `y(um)`, `z(um)`: Move stage in micrometers along X, Y, Z.
    
- `stagehome`: Set current XYZ position as home.
    

---

### 🌡️ **Misc Functions**

- `rldr`: Read light-dependent resistor for laser detection (used in autocal).
    
- `autocal`: (TBD)
    
- `mshut`: Close mechanical shutter.
    
- `mopen`: Open mechanical shutter.
- `ramanmode`: Set system to Raman acquisition mode.
- `imagemode`: Set to widefield image acquisition mode.
- `polin(angle)`, `polout(angle)`: Set polarizer angle (entry/output).
- `wai`: (TBD)
- `wavelengthaxis`: (TBD)
- `acqtime`, `filename`, `ramanshift`, `laserpower`: (TBD – placeholder or legacy)




# Re-aligning the gratings
If the Raman signal is lost completely, follow the
[grating alignment quickstart](grating_alignment_quickstart.md).

# Achieving Kohler illumination
1. adjust the X and Y translation knobs on the Optimecanic mount holding the white light fiber optic cable to align the light to the center of the microscope objective at the sample. You will optimise for sample brightness on the camera.
2. Slide the focusing lens until the spot on the sample


# Legacy Modifications
This section contains notes for modifications that were carried out to the microscope. Their inclusion here is only for context and legacy maintenance, in case something needs modification again in the future.

## Goals:
- Flip the X-Y translation optomechanic mount 180 degrees so the X knob points out to the right
- Install the X-Y cage-mounted optomechanic to hold the image focusing lens to the camera.
- Push back the camera to allow longer focal length lenses to fit in the camera image focusing section.

## Flipping the XY optomechanic
1. Unscrew the post clamp holding the XY optimecahnic. Remove the optomechanic from the table, including the cage rods.
2. Unscrew the cage rods from the optomechanic and slide the AC80 lens off the rods. Make note of the orientation of the lens with respect to the fiber optic cable.
3. Remove the SM1FC2 threaded fiber optic adapter from the XY mount.
4. Flip the mount 180 degrees and re-thread the SM1FC2 adapter into the side of the XY mount that moves (twist the micrometers to see what side moves).
5. Screw the cage rods into the other, flipped face of the XY translation mount.
6. Place the AC80 lens back on the cage rods in the same orientation with respect to the whole optomechanic mount/fiber optic cable.
7. Place the mount back on the table, and push the cage rods back into the white 30-60 adapter. It can help to loosen the cage rods to get all of them into the white adatper, then tighten them back down once in place.
8. Screw the fiber optic back in and refocus/realign the white light source into the back of the microscope objective. Note the camera needs to be aligned to fully focus/align the white light source.

## Install XY translation cage mount
1. Remove the 4x microscope objective in the camera section from the cage.
2. Attempt to slide the whole camera section (cage rods included) from the white 30-60 adapter. If it doesn't come out loosen some of the cage rods on the camrea box/mount
3. Once the camera is free from the white adapter, extend or replace the cage rods. Make sure they are long enough to create enough space to put the lens in (75-100 mm) but not so long that they push the camera over the edge or extend the rods into the beamsplitter section.
4. Place the XY cage translation mount on the cage rods.
4.5 place a lens in the adapter
5. Slide the cage rods and camera back into the white adapter.
6. Lock the camera post mount down to the table

## Aligning the light source and camera
Perform this step with the beamsplitters in the optical axis ("image mode").
1. Focus the laser to a flat, reflective sample. Use a target card mounted in the cage section just before the beamsplitters. Focus is achieved when the back reflected laser light strikes the targer card on return, and is roughly the same size as the input aperture on the target card.
2. **Focus to the camera**. Slide the lens along the cage rod until the laser spot is focused as small as possible on the camera. Centre the spot on the camera display using the X-Y translation knobs on the lens mount.
    - Not the spot might not be perfectly centred with the XY translation knobs and this is fine.
3. **Align and focus the illumination**. Use the X-Y translate to maximise illumination on the sample, as seen by the camera. Slide the collimating lens along the cage slightly to improve intensity at the sample. You want high brightness and even illumination. Technically best illumination (Kohler illumination) is achieved when the light is uniformly spread over the image region, but with thin 2D materials sometimes overfocusing so that the light becomes more concentrated in the centre can improve contrast and assist in viewing of flakes. 
4. Iterate steps 2-3 until the image (of a flake) is sharp and evenly illuminated.


- FYI Camera module in "4. Adapters > ThorCam PCB"

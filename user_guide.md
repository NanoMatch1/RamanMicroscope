# DRR Working Notes
## Microscope startup and initialisation

1. Boot the software by running the `interface_run_me.py` script. **ENSURE the power to the motors is OFF**.
2. Once provided a `Enter command` promt, turn on the motor power at the controller switch.
3. Type `enable` to begin first phase of laser warmup
4. `homelaser` to home all laser motors
5. `homegratings` to home all grating motors
6. Use `sall` $\lambda$ to go to a specific wavelength. 
    - NOTE: A go-to command is required after homing any motor.
    - Homing motors brings them to the zero steps position. All motots at zero does not equate to any calibrated wavelength, so a go-to command is required to realign to a chosen wavelength.
7. If not yet done, open or cycle the shutter `cycleshutter` or `shutteron`
8. Confirm the laser is lasing at the desing wavelength. At the desing wavelength, the laser will make it to the pinhole and should pass through the rest of the microscope to the sample. 
- **Troubleshooting**: If the laser does not lase properly, or is weak, sometimes the l2 motor is not where it should be after homing (this is not common but can happen). Rehome just l2 with `home l2` and follow up with `sl` $\lambda$. If this does not fix it, manually jog the motor until lasing is restored. Find the motor positon that centres the alignment on the lasing condition, then use `reference` $\lambda$ to reference this set of motor positions to this wavelength.
9. Ensure lasing at the sample (sulfur test).
10. Type `run` to initiate the continuous acquisition for focus and alignment. NOTE: The `data_viewer_run_me.py` should be running in a separate window. If not, go to the RamanMicroscope code folder and run this file by double clicking.
11. In the data viewer UI, ensure the ROI start and end are set to a logical range. Usually 100-2000 respectively. Toggle autoscale as required to view the spectrum and lock/normalise the intensity range. 
12. Also ensure the Y centre and Y width are set to capture the data. This is the binning on the CCD array, and the data should be centred around pixel 83 with ~10 pixel range. On rare occasions, this can change, so if no peaks are present try widening the Y width value (and click Apply Y ROI) 
13. Upon running, the data viewer should update with live data each frame. The sulfur spectrum should be just barely visible at 1 second acquisition time if you're lucky. Not not:
    1. Check the sample is in focus 
    2. **the motors may need to be jogged into alignment**

### Jogging motors:
After homing, sometimes the motors can be slightly off still. I believe this is a consequence of inaccuracy in the limit swicth positions and the absolute positioning of the grating motor drivers. The fix is to massage the setup into its final alignment.

1. start with motor G1. You can place a target card in the cage system near the 45 degree vertical turn (just after the beamsplitters). The laser should pass dead centre through the target card. If not, use `g1 x` to move the motor x steps. Do this until it passes through the target card centre.
2. Remove the target card.
3. Next, work through the other motors by observing changes to the spectrum. 
    - g2, g3, g4
    - The intensity should reach a maximum within 1-3 steps of thier current positions. Find the maximum value for the motor, then move on to the next.
    - Once all motors have reached their maximum intensities, you can cycle back and repeat once more.
    - Once you are satisfied with the intensities, reference this position (`reference` $\lambda$) and move on.

The microscope should now be aligned and calibrated, ready for scans.

# Running a Scan
The scanning controls are currently all managed with a separate UI. Type `gui` to load this UI.
Here you can select start and end positions and resolution for all scan dimensions: Stage motion, wavelength, and polarization. You can also edit filename and acquisition time.
Select settings as desired
Tick the box to "enable scan mode"
Click "start scan acquisiton" to begin scanning acquisition.

The files are saved to a folder of the filename, inside the data directory of the main RamanMicroscope folder. These will be processed later by analysis scripting.

# Troubleshooting




# Control Notes

The primary form of interaction with the microscope is via the command line interface. This will change over time to a Graphical User Interface, but the command line interface will always be accessible for debugging and convenience.

## How To Use Commands
All commands can be passed arguments in the form of characters separated by `<space>` keys. For instance, `sl` is the "go to laser wavelenght command", and it requires a laser wavelength as a number for it's argument. The command to move to 750 nm laser excitation is `sl 750`.

### Frequent Commands
- `wai`: "whera am I" prints the current motor positions and calculates the laser and grating wavelengths using the calibrations
- `sl` $\lambda$: set laser wavelength to specified value (e.g. `sl 800` for 800 nm)
- `sg` $\lambda$: set wavelength on all gratings (microscope filter and double monochromator)
- `sm` $\lambda$: set wavelength on just the monochromator gratings. Useful for moving the dection closer to the laser line (for seeing low-frequency modes) or further from the laser line (to reduce stray light and rayleigh scattering signal)
- `st` $\lambda$: set TIRAX spectrometer wavelength
- `sall` $\lambda$: set all wavelengths (for changing the whole setup to a specific wavelength)

- `homelaser`: homes the three laser motors in sequence
- `homegratings`: homes all graing motors in sequence
- `home` $motorlabel$: homes the motor of $motorlabel$ (e.g. `home l1`)

- `reference` $\lambda$: reassigns the current motor positions to the wavelength of choice. Used when making minor adjustments to the alignment of the laser or gratings.

- `ren`: read enterance slit on the spectrometer. Should be between 25 and 50 microns for standard operation
- `men`: move enterance slit on the spectrometer.


- `run`: runs the camera in continuous acquisition mode. Data is plotted to the data_viewer_run_me.py
-`stop`: stops a continuous acquisition.
- `filename` $string$: sets the current filename ($string$) for saved data
- `gui`: brings up the GUI for preparing and performing multidimensional scan datasets

- `enable`: cycles through the startup sequences of the laser. Reperated calls to `enable` progress the startup sequence:
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
    
- `roi(x, y, width, height)`: Set region of interest.
    
- `setbin(binning_level)`: Set pixel binning.
    
- `setgain(value)`: Set camera gain.
    
- `camspec`: Switch to spectrum mode.
    
- `camimage`: Switch to image mode.
    
- `acquire`: Acquire a single frame (if implemented).
    
- `run`: Start continuous acquisition.
    
- `stop`: Stop continuous acquisition.
    

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




Notes for Riley
1. Adjust intermediate filter in monochormator so that the spectrum cuts off at lower wavenumbers, closer to the laser line.
- Trying to avoid cutting into the low-frequency modes between 100 and 300 cm-1
2. see if the cutoff changes at all wavelengths, ~10 nm steps
- us mos2 powder to see the effect, ~5s 
3. Build the sample stage for high magnification oil immersion lenses inspired by thesis design
4. Perform a linescan


# Data access
https://unimelbcloud-my.sharepoint.com/:f:/g/personal/rileyjt_student_unimelb_edu_au/ElSFjKdas_NDlLl6kADVAnUBTr1sApV6YKhTFq065Ky97w?e=5%3a3r9Vvt&at=9


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


# Notes adn ToDo:

## Riley's Research plan/literature survey
The first aim is to identify and characterise defect modes in other TMDs. This analysis is firstly, novel, given that the defect modes of many TMDs are largely unexplored in general, and completely unexplored under indirect resonance conditions. Secondly, the use of the Raman microscope to comprehensively explore these model systems provides a basis for applying the setup to investigate other defect systems and quantum devices by demonstrating the types of defects that can be investigated, and how exactly selection rules are affected/what to expect in other systems.

We will use the materials avalaible to gain insights sequentially and with increasing complexity. MoS2 serves as the initial validation. The defect modes will be identified and characterised at different wavelengths to validate the setup and provide novel insights beyond published works. WSe2 is the next candidate, and is sufficiently unexplored under DRR to provide publishable results (need to check recent literature for any work in the defect modes of WSe2)

The initial reserach plan is as follows:
1. Validate the DRR setup by studying MoS2
- there will be a burn in phase where teething issues and calibration need to be addressed. MoS2 is well understood by the team and will provide a nice benchmark for the setup.
- Actions:
    - Defect wavelength scan on MoS2 powder
    - Line scan on MoS2 flakes, oil immersion lens
2. WSe2 - Fronteer of research
- Actions:
    - Check literature for recent advances/publication on defect modes
    - Run powder wavelength scans to identify defect modes
    - perform linescans, maps, and polarization studies to fully map the resonant defect behaviour of flakes under the high NA objective

3. InSe - Strain stuff
4. Other sytems incl. polaritons





--> investigate solar materials once the setup is validated.

## Sam ToDo:
- create dummy instrument classes for dependency injection.
- create unit tests for all classes
- Ensure scan parameters updating to metadata
- compress data saving
- Add simple start-stop UI with save database and load pipelines
- check json calibration
    - work on calibration modifying script
- code solutions for Dark Signal Non Uniformity and Photo Repsonse Non Uniformity

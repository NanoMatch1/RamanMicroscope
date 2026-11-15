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
12. Check the camera ROI: the CCD rows that make the spectrum (see "How it works: Camera region of interest and binning" in the [command reference](command_reference.md)). The application sets the stored ROI at start-up and says so; if the slit image has moved (after any work on the camera or spectrograph), set it again before collecting data.
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

# Commands

The microscope is driven from the command line: type a command and its arguments separated by spaces, e.g. `sl 750` to move the laser to 750 nm, or a motor label and a number of steps to jog that motor, e.g. `g1 5`. Every command, with its arguments and examples, is in the [command reference](command_reference.md), generated from the code; `help` prints the same text at the prompt. The reference also explains the camera: live view and acquisitions, exposures, and the region of interest and binning.


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

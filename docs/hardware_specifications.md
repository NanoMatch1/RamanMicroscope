# Hardware specifications

One place for the instrument's physical facts: models, focal lengths, groove densities, pixel
sizes, beam sizes and geometry. Optical models, alignment procedures and analysis scripts take
their numbers from here, so each value says where it came from and how far to trust it.

**Values the code uses are not repeated here.** Where software reads a number (for example the
CCD's nm per pixel, or a motor's steps per nm), the config or calibration file is the source,
and this page points to it. Copying such a number here would make two homes for it, and one
would go stale.

**How to fill it in:**
- **Source** is one of:
  - `datasheet`: the manufacturer's figure (name the document or the part number in Notes);
  - `measured`: measured on this instrument (give the date, the method, and the lab-notebook
    finding ID if there is one);
  - `estimate`: a value from memory or a quick look, good enough for a first calculation;
  - `to check`: unknown.
- **Checked** is the date the value was last confirmed on the bench (YYYY-MM-DD).
- Replace an `estimate` with a `datasheet` or `measured` value when you can, and keep a note of
  the old value in Notes if they disagree.
- This repository is public: leave out serial numbers, asset tags and purchase details.

Axes: "horizontal" and "vertical" mean in the lab frame at the component, unless a row says
otherwise. The periscope between the filter stages swaps them (see Tunable filter).

## Excitation

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Pump laser | JenLas JOL-D2.10 (Jenoptik) | to check | | Model reported from the lab in 2026-10; confirm the name on the unit. Interface: RS-232. |
| Pump wavelength, power | ? | to check | | |
| Tunable laser | Ti:sapphire, grating-tuned ("Tiger-200") | to check | | Replaced a Spectra-Physics Tsunami. Interface: RS-232, piezomotor. |
| Tuning range | ? | to check | | Software hard limits are in `microscope_config.json` (`hard_limits`). |
| Linewidth | ? | to check | | |
| Output beam diameter, divergence | ? | to check | | |
| Power at the sample | ? | to check | | Per wavelength, if it varies. |
| Laser tuning motors (l1-l3) | ? | to check | | Motor and driver model; what each one moves. |

## Tunable filter (double subtractive monochromator)

Two stages. Stage 1 (g1/g2) is nearest the microscope and holds the laser injection mirror;
stage 2 (g3/g4) is nearest the spectrograph. `docs/stage1_edge_measurement.md` section 2 shows
the stage 1 light paths.

### Stage 1

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Gratings g1, g2: groove density | 1200 grooves/mm | estimate | | Blaze, size and ruled/holographic: to check. |
| Lenses (collimating and refocusing) | f = 50 mm singlets | estimate | | Temporary: chosen for the tight geometry. Glass, diameter and part number: to check. |
| Lens tilt | near zero | estimate | | Kept as small as possible during the build. |
| Beam diameter through the stage | about 1-2 mm | estimate (2026-11-17) | | Measure at g1, e.g. with an iris or a card. |
| Injection mirror | 45 degree mirror with a cleaved edge, at the intermediate focus | estimate | | The edge is the stage 1 cutoff. Coating and size: to check. |
| Angle between the forward (laser) and backward (alignment) paths | about 21 degrees | estimate | | Consistent with the 608-step alignment move. |

### Periscope (between the stages)

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Geometry | entrance and exit at right angles | estimate | | Swaps the horizontal and vertical axes: stage 1's dispersion plane lies along the TRIAX slit. |
| Mirrors | ? | to check | | |

### Stage 2

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Gratings g3, g4: groove density | 300 grooves/mm | estimate | | Blaze and size: to check. |
| Focusing optics | curved mirrors, f = 500 mm | estimate | | Built before stage 1. |
| Edge | removable | estimate | | Removed for the stage 1 edge measurement. |

### Grating motors

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Rotation per step, g1-g4 | about 17.6-18 mdeg per step | measured (2026-11-16) | | Derived from the master calibration; all four gratings agree. |
| Microstepping | 32 | estimate | | From the name of the calibration file, `calibration/master_calibration_microsteps_32.json`. |
| Motor and driver models | ? | to check | | |
| Limit switches | ? | to check | | Position and repeatability of the home switches. |

## Microscope

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Objective (Raman) | ? | to check | | Magnification, NA, focal length, working distance, NIR correction. |
| Objective (camera/white light path) | 4x | estimate | | From the white-light realignment notes in `docs/user_guide.md`. |
| White light source | fibre-coupled lamp | estimate | | Model and fibre core: to check. |
| Pinhole | ? | to check | | Diameter; where it sits. |
| Polarisers (p_in, p_out) | ? | to check | | Type, extinction ratio, motor. |
| Sample stage (x, y, z) | ? | to check | | Travel, step size. |

## Spectrograph and detector

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Lens into the TRIAX | f = 75-100 mm | estimate (2026-11-17) | | Exact focal length and diameter: to check. |
| Spectrograph | HORIBA TRIAX 550 | datasheet | | Interface: RS-232. |
| Grating in use | 300 grooves/mm, 600 nm blaze | to check | | Other gratings on the turret: to check. |
| Entrance slit | opens symmetrically | measured | | Driven by a stepper; a pin drives up between two blocks. |
| Detector | Princeton Instruments PIXIS | to check | | Exact model (e.g. 1024BR), chip size. Interface: PICam SDK via `pylablib`. |
| PIXIS pixel pitch | 13 um | to check | | The CCD's nm per pixel comes from the master calibration (`wavelength_axis`), not from this value. |
| Previous detector | Tucsen | estimate | | Pixel size 6.5 x 6.5 um. Used for older data, e.g. `docs/demo_data/`. |

## Calibration and alignment sources

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Line lamp | Ar-Hg | to check | | Model. |
| Broadband lamp | halogen, NIR | to check | | Model and output range. A lamp for the 720-960 nm range is being sourced. |
| Aperture cards (stage 1 edge measurement) | ? | to check | | Hole diameters and spacing on the rails: see `docs/stage1_edge_measurement.md`. |

## Electronics

| Item | Value | Source | Checked | Notes |
|---|---|---|---|---|
| Motion controller | Arduino MEGA, 4 modules of up to 4 axes | measured | | USB serial; protocol: `arduino_mega_develop/`. Motor IDs are `[module][axis]`, e.g. `3Z`. |
| Stepper drivers | ? | to check | | Model, current setting. |
| Lab PC | ? | to check | | OS and Python version, for reproducing runs. |

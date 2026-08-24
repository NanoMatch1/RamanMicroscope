# tools/

Standalone diagnostic, calibration and exploration scripts. **Nothing here
is imported by the application** — these are run by hand, usually against
real hardware, and they encode findings that were expensive to obtain.

They were moved here from the repository root and from `instruments/` in
the Gate 3 cleanup so that the package directories contain only code the
application actually loads.

Be aware that most of these hard-code COM ports and absolute paths; read
before running. See `MODERNIZATION.md` 1.4.

| Script | Purpose |
|---|---|
| `sdk check.py` | Princeton Instruments PICAM/pylablib SDK exploration. The largest reference here (~88 KB) — interactive menu covering exposure, ROI, temperature and TRIAX interaction. Written during the Tucsen→PIXIS port. |
| `Lasercalbration.py` | Tiger laser wavelength-calibration data collection, driving the laser and TRIAX together. Source of the verified points in `instruments/lasers/tiger_calibration.py`. |
| `triax_connection_test.py` | TRIAX RS-232 connection and handshake diagnostics. Useful when the spectrometer will not initialise. |
| `Riley Triax Test.py`, `Riley triax driver test.py` | Earlier minimal TRIAX serial probes. |
| `Lasercomstesttiger.py`, `laser_coms_test.py`, `lasercommprobe` | Tiger RS-232 command probes from the laser bring-up. |
| `Calibrationgenerator.py` | Generates calibration files. |
| `recalibrate_function.py` | Recalibration helper. |
| `spectrum_generator.py` | Synthetic spectrum generation. |
| `dataset_post_processing.py` | Post-processing over acquired datasets. |
| `logging_test.py` | Exercises `logging_utils.LoggerInterface`. |
| `cal1.csv`, `calitest.csv`, `motor_tests.json` | Captured data from the above runs. |

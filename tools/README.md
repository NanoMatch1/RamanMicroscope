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
| `pixis_frame_freshness_check.py` | Does a camera grab return a frame exposed after the request? Measures the streaming grab (the live view `run`, and `grab_frame` before 2026-11-06) against the on-demand acquire `grab_frame` now uses (start, wait, read, stop), judged by exposure time stamps, plus ROI, readout time, frame period, temperature and shutter settings. Run with the application closed; report in `data/camera_checks/`. Written for the 2026-11-05 stale-frame audit. |
| `pixis_dark_noise_check.py` | Read noise against dark current, to choose the frame length for long points (`nframe`). Dark frame pairs at several exposures (light blocked): bias, dark rate, read noise, a conversion-gain estimate, hot pixels and light leaks per pixel; the data ROI binned on the chip measured directly against software binning; optionally at each ADC speed (`--adc-speeds 0.1 2`). Run with the application closed; report in `data/camera_checks/`. Written 2026-11-11. |
| `Lasercalbration.py` | Tiger laser wavelength-calibration data collection, driving the laser and TRIAX together. Source of the verified points in `instruments/lasers/tiger_calibration.py`. |
| `triax_connection_test.py` | TRIAX RS-232 connection and handshake diagnostics. Useful when the spectrometer will not initialise. |
| `Riley Triax Test.py`, `Riley triax driver test.py` | Earlier minimal TRIAX serial probes. |
| `Lasercomstesttiger.py`, `laser_coms_test.py`, `lasercommprobe` | Tiger RS-232 command probes from the laser bring-up. |
| `Calibrationgenerator.py` | **Non-functional, kept for reference.** Refitted the CCD pixel calibration from live-calibration output, which is circular; superseded by `speccal` (`docs/calibration.md`). |
| `recalibrate_function.py` | Recalibration helper. |
| `migrations/migrate_master_to_wavelength_axis_group.py` | One-off (2026-11-03): moved the TRIAX and CCD calibrations in the master file into one `wavelength_axis` group. Kept as a record; refuses to run twice. |
| `spectrum_generator.py` | Synthetic spectrum generation. |
| `dataset_post_processing.py` | Post-processing over acquired datasets. |
| `repo_guard.py` | **The exception: run by the pre-commit hook and CI, not by hand.** Blocks personal emails, home-directory paths, share links, data files, large binaries and personal commit identities. `python tools/repo_guard.py list` shows the checks. |
| `logging_test.py` | Exercises `logging_utils.LoggerInterface`. |
| `cal1.csv`, `calitest.csv`, `motor_tests.json` | Captured data from the above runs. |

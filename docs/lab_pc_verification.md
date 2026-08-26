# Lab PC verification procedure

**Purpose:** confirm that a version of this repository actually drives the
microscope, on the machine that has the hardware attached.

**When to run it:** after any `git pull` onto the lab PC, after a Python or
driver reinstall, and after any hardware is swapped or moved.

**Who runs it:** whoever is at the bench. It needs physical access to the
instrument for stages 4 and 5.

The stages run cheapest-first and least-dangerous-first. Each one narrows
where a fault can be. **Do not skip ahead** — if stage 1 fails, nothing
after it is meaningful, and stage 4 moves real motors.

Record the result of each stage. There is a copy-paste report template at
the bottom.

---

## Stage 0 — Before you pull

The lab PC has historically carried large uncommitted changes in its
working tree (this is how the Tiger/PIXIS migration reached the maintainer).
A `git pull` on top of those will either refuse or produce conflicts, and
in the worst case silently discards weeks of bench work.

```bash
cd path\to\RamanMicroscope
git status
```

**If the tree is dirty, stop and preserve it before doing anything else:**

```bash
git stash push -u -m "lab PC state before pull YYYY-MM-DD"
git stash list                     # confirm it is there
```

Then pull:

```bash
git fetch origin
git log --oneline HEAD..origin/develop     # read what is about to land
git pull origin develop
```

Afterwards, tell the maintainer what was in the stash:

```bash
git stash show -p stash@{0} > stashed_lab_changes.patch
```

Send that patch file. Do not try to merge it yourself — some of it may be
deliberate local configuration, and some may be work worth keeping.

> **Never `git checkout -- .` or `git reset --hard` on the lab PC** to make
> a pull go through. That is unrecoverable. Stash instead; a stash can
> always be dropped later, but it cannot be un-deleted.

### Files that are *supposed* to differ on this machine

These are gitignored on purpose and record where this rig's hardware
physically is. They must never be committed, and a pull must never change
them:

- `calibration/tiger_step_position.json` — the only record of the Tiger
  piezomotor's absolute position
- `instrument_state.json`
- `acquisitioncontrol/acquisition_config.json`
- `acquisitioncontrol/viewer_settings.json`
- `instrument_errors.log`

If a pull ever tries to modify one of these, something is wrong with the
`.gitignore` — report it rather than working around it.

---

## Stage 1 — Tests, no hardware needed

This is the real "does this version work" gate. It runs the entire
application in simulate mode through the real command handler, with no
instrument attached. **It is safe to run at any time, including while an
experiment is running**, because it touches no ports.

```bash
python -m pytest test_controller_simulated.py test_headless_simulation.py -q
```

**Expected: `29 passed`** — 9 Arduino-protocol unit tests + 20 full
workflow tests.

| Result | Meaning | Action |
|---|---|---|
| `29 passed` | The code is internally consistent on this machine. | Continue to stage 2. |
| Collection error / `ImportError` | A dependency is missing or a Python version mismatch. | Stage 2, then retry. |
| Any test fails | A real regression. | **Stop.** Send the full output to the maintainer. Do not proceed to hardware. |

If the run hangs instead of finishing, that means something in the code is
waiting on `input()`. That is a bug, not an environment problem — report it.
The suite deliberately replaces stdin with an empty stream so prompts fail
fast rather than hang, so a hang means a prompt slipped past that guard.

---

## Stage 2 — Environment

Only needed if stage 1 failed, or after a Python reinstall.

```bash
python --version
python -m venv .venv                       # if there isn't one already
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` is fully pinned — that is deliberate. It is the record of
the exact versions this instrument is known to run on. Do not upgrade
packages to make an error go away; report the error instead.

### Dependencies that pip does **not** install

These have to be present on the machine independently, and they are the
usual cause of a "worked on the dev laptop, fails here" report:

| Dependency | Needed by | How to check |
|---|---|---|
| **Princeton Instruments PICam SDK** | `pylablib` → `PIXISCamera` | Camera appears in PI's own software |
| **Arduino MEGA on the expected COM port** | `controller.py` | Device Manager; see stage 3 |
| **Arduino firmware** from `arduino_mega_develop/` | motor protocol | Only if motors misbehave — reflash from this repo, it is the ground truth |

Re-run stage 1 before continuing.

---

## Stage 3 — Simulate-mode startup

Confirms the application builds every object and registers every command,
still without touching hardware.

```bash
python interface_run_me.py
```

**Before anything else, check which mode it started in.** The startup
banner and log should make this obvious.

> ### ⚠️ How simulate mode is currently decided
>
> `interface_run_me.py` (bottom of the file, in `__main__`) picks simulate
> mode by inspecting the working directory and platform:
>
> ```python
> if "Users\\Sam" in os.getcwd():   simulate = True
> elif sys.platform == 'linux':     simulate = True
> else:                             simulate = False
> ```
>
> On the lab PC (Windows, `C:\Users\Raman\...`) this evaluates to
> `simulate = False`, i.e. **live hardware**. That is the correct outcome,
> but it is decided by a path string, not by an explicit choice.
>
> **If you ever see the app connect to real hardware when you expected a
> simulation, or vice versa, that is this heuristic — say so.** Replacing it
> with an explicit `--simulate` flag is tracked as `MODERNIZATION.md` 1.5.
>
> To force simulation for now, run from a directory that trips the check, or
> call `main(simulate=True)` — **do not** edit the module-level line and
> leave it edited. A committed `simulate = True` would make the real
> microscope silently do nothing while reporting success.

At the prompt:

```
help
exit
```

`help` should list the full command set. If commands are missing, the
registry self-check (`_integrity_checker`) has diverged from
`command_functions` — report which commands are absent.

---

## Stage 4 — Hardware, one subsystem at a time

**From here on, real motors move.** Before starting: make sure the beam
path is clear, the sample stage has clearance, and you know where the
laser shutter control is.

Start the application live (stage 3, but on the lab PC with hardware
connected and powered).

### 4a. Arduino controller and motors

```
allmotors
```

Expected: a dictionary of every motor label (`l1`, `l2`, `l3`, `g1`–`g4`,
`triax`, stage axes) with integer step positions.

| Symptom | Likely cause |
|---|---|
| Serial/COM error on startup | Wrong port. The port is **hard-coded as `COM10`** in `interface_run_me.py` (`main()`). Check Device Manager and report the real port — do not just edit it silently, it needs fixing properly (`MODERNIZATION.md` 1.4). |
| Connects, but positions are all zero or absurd | Firmware/protocol mismatch. Compare against `arduino_mega_develop/`. |
| One motor missing from the dictionary | `action_groups` mapping in `microscope.py` vs. the physical wiring. |

Then a small, reversible move on one motor, and confirm it reports back:

```
allmotors
stepup            (or a single-motor step command for a safe axis)
allmotors
```

### 4b. Laser (Tiger)

```
connectlaser
laserstatus
getpower
gettemp
laserpos
```

Expected: status returns, power reads a plausible number, temperature is
sane, and `laserpos` gives the piezomotor position.

Note that `calibration/tiger_step_position.json` is this machine's only
record of the Tiger's absolute position. If it has been deleted or reset,
the next relative move will be wrong. Check it looks plausible before
moving the laser.

### 4c. Spectrometer (TRIAX, RS-232)

```
initialise
get_spectrometer_position
```

Expected: initialise completes, position reads back a real value.

The TRIAX was rewired from GPIB to RS-232. If you see any error mentioning
`pyvisa` or GPIB, that is leftover code from before the rewrite — report
it with the traceback; two such leftovers have already been found and
fixed this way.

### 4d. Camera (PIXIS)

```
camopen
caminfo
temp
acqtime 1
acquire
```

Expected: `caminfo` returns a populated dictionary; `temp` reports the
detector temperature; `acquire` returns a frame of the PIXIS sensor width.

> **Units check:** `acqtime` is **in seconds**. A previous version of the
> config carried `acquisition_time: 100.0` from before a unit fix — which
> is 100 seconds, not 100 ms. If an acquisition seems to hang, check this
> first.

Let the detector reach its set temperature before judging any spectrum.

---

## Stage 5 — Integrated: the thing the instrument is for

```
homeall
sl 800
wai
acquire
```

This exercises the full chain — home all axes, drive the laser and
monochromator to a wavelength, report where the instrument thinks it is,
and acquire.

Check that:
- Homing completes on every axis without stalling.
- `wai` reports a wavelength consistent with what you asked for.
- The acquired spectrum has the expected peak position for a known
  reference sample (silicon at 520 cm⁻¹ is the usual check).

If the wavelength is systematically off, that is a calibration question,
not a code question — the calibration files under `calibration/` are the
place to look, and recalibration is a separate procedure.

---

## Open hardware question — please answer this one

Tracked as `MODERNIZATION.md` 2.3. It needs somebody at the instrument:

> **Has a limit switch been fitted to the mode motor (`2A`), the one that
> switches between Raman mode and imaging mode?**

Why it matters: mode switching currently steps open-loop by ±100000 steps
with nothing to home against, so a single lost step silently mis-positions
the mode mechanism and nothing detects it. If a limit switch exists on
`2A`, the `h2A` homing command already in the firmware would make mode
switching self-correcting.

The complication: the firmware defines only **one** shared
`homingLimitPin = 13`, so there are no per-motor endstops. Answering this
needs a look at the actual wiring, not just the code.

Please report: (a) is there a switch on 2A, (b) if so, what pin is it
wired to, (c) is anything else sharing pin 13.

---

## Report template

Copy, fill in, send to the maintainer.

```
REPO VERIFICATION — lab PC
Date:
Commit:            (git rev-parse --short HEAD)
Python version:
Ran by:

Stage 0  pull            [ pass / fail ]  stash created? [ yes / no ]
Stage 1  tests           [ pass / fail ]  result: ___ passed / ___ failed
Stage 2  environment     [ pass / fail / skipped ]
Stage 3  simulate start  [ pass / fail ]  mode reported: [ simulate / live ]
Stage 4a Arduino+motors  [ pass / fail ]  COM port actually used: ____
Stage 4b laser           [ pass / fail ]
Stage 4c spectrometer    [ pass / fail ]
Stage 4d camera          [ pass / fail ]
Stage 5  integrated      [ pass / fail ]  Si 520 cm-1 seen at: ____

Limit switch on mode motor 2A?  [ yes / no / unknown ]

Anything unexpected (paste tracebacks in full):
```

---

## If something fails

1. **Capture the full traceback.** Not a screenshot of the last line — the
   whole thing, as text.
2. **Note which stage failed**, because that localises the fault: stage 1
   is code, stage 2 is environment, stages 4–5 are hardware or calibration.
3. **Do not fix it by editing tracked files and leaving them edited.** If a
   local edit is needed to get running, say so explicitly — an undeclared
   local edit on the lab PC is how the repository and the instrument drift
   apart.
4. Open an issue, or send the report template above.

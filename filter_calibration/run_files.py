"""
The run files for calibrating g1 against the stage 1 cutoff edge, for the `runfile` command.

What is measured: the stage 1 edge (the laser-injection mirror's cleaved edge) seen on the CCD
through a broadband lamp spectrum, as g1 turns. The edge position against g1 steps calibrates g1;
the edge width against wavelength measures how sharp the cutoff is across the range (the
collimating lens's chromatic focus shift is expected to broaden it away from one wavelength).

g2 follows every g1 move. The edge is set by g1 alone, but g1 turned on its own also turns the
beam leaving stage 1: on 2026-11-17, g1 moved alone dimmed the light many times over within 20
steps and lost it entirely at 150. So each g1 move is paired with the g2 move that keeps the
pair matched, at the ratio the master calibration gives at that centre (d g2 / d g1 at fixed
wavelength, about -1). Stage 2's intermediate slit must be out, or its edge hides stage 1's.

The TRIAX entrance slit is wide (about 500 um). The filtered light reaches the slit as a spot
narrower than 200 um, so a wide slit passes all of it and neither moves nor blurs the edge,
while a 50 um slit clips the spot by an amount that changes with wavelength (lab-notebook
RAM-F5). The Ar-Hg axis references are the exception: they are taken at about 50 um, because
at 500 um the lamp lights a different part of the slit from the filtered light (RAM-F6).

The edge session's four run files, written to data/runfiles/ (per machine, not tracked):
- stage1_edge_walk.txt: at each centre wavelength, the TRIAX put so that wavelength lands mid-chip
  ('st' alone puts it on spectrometer_target_pixel, near the short-wavelength end, and the
  edge would leave the chip) and 'sg' to it, then frames at g1 offsets around it (default -20
  to +20 in 10s, about +/-9 nm), each approached from below, plus one frame with g1 at +150
  steps and one at -150 (edge-free frames, one each side: open and closed, whichever way the
  edge moves). g2 follows g1 throughout.
- stage1_single_steps.txt: at one centre, g1 in single steps over -20..+20 from below, then
  back down five single steps (step uniformity, sub-step precision, backlash), with g2
  following.
- stage1_repeatability.txt: at one centre, frames after returning to it in different ways,
  interleaved in cycles: nothing moved, the TRIAX alone away below and above and back, and the
  gratings alone ('sg') away below and above and back. Only one thing moves before each frame,
  so a change in the edge reading says which one does not return to the same place: the TRIAX
  (the frame's wavelength axis) or the gratings (the edge). Interleaving puts any slow drift
  of lamp or temperature into every kind of frame alike, and the still frames measure it. On
  2026-11-18 three visits to 800 nm read the edge at 803.07, 803.47 and 803.76 nm (RAM-F5).
- stage1_axis_references.txt: the Ar-Hg lamp in place of the halogen, slit at about 50 um, one
  frame at each centre's TRIAX position. The TRIAX's wavelength axis is off by a different
  amount at each position (up to about +/-0.13 nm, RAM-F3), and its zero can move between
  sessions (RAM-F1), so the analysis corrects each centre's edges with the argon lines in that
  centre's own frame. The TRIAX repeats a position to about 0.003 nm when it is reached the same
  way, which 'st' always does (from below).
And, for a later step with a pinhole in the beam (two files, one per pinhole position):
- stage1_g2_pinhole_stage2.txt (pinhole on stage 2's entrance port axis, the reference) and
  stage1_g2_pinhole_stage1.txt (pinhole at stage 1's exit port, a one-off cross-check): at each
  g2 centre, 'sg' there, then g2 alone in single steps across the pinhole (default -25..+25,
  from below), one frame per step. g1 stays where 'sg' put it, so the edge sits at the centre
  wavelength and the light passes on the long side of it. The CCD is the detector: the light
  through the pinhole against the g2 count is a window whose centre is where g2 points the beam
  through the pinhole's centre (pinhole_scan.py). g2 turns the beam about 0.6 mrad per step, so
  the beam crosses a 1 mm pinhole half a metre away in a few steps; the halogen beam is wider
  than that, and the scan traces its profile. The band also moves along the slit with g2 (about
  3-5 rows per step on 2026-11-18), so the frames must read the whole sensor (no camera ROI).
Frame names follow frame_names.py. 'allmotors' before each frame puts the grating positions into
the run log, 'rg' the TRIAX steps and 'ren' the slit width.

Bench set-up, the reasoning, and the steps by hand around these files (reference frames, the
laser-excited run): docs/stage1_edge_measurement.md. The analysis: `python -m filter_calibration
fit` (filter_calibration/__main__.py).
"""

import json
import os
from dataclasses import dataclass

import numpy as np

from .frame_names import (PINHOLE_POSITIONS, START_VISIT, STILL_VISIT, axis_reference_name,
                          edge_walk_name, g2_pinhole_scan_name, gratings_visit,
                          repeatability_name, single_step_name, triax_visit)

REPOSITORY_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIRECTORY = os.path.join(REPOSITORY_DIRECTORY, 'data', 'runfiles')
DEFAULT_TRIAX_CENTRES_NM = (720, 760, 800, 840, 880, 920, 960)
DEFAULT_EDGE_OFFSETS_STEPS = (-20, -10, 0, 10, 20)
EDGE_FREE_OFFSET_STEPS = 150        # about 67 nm of g1: well off the +/-40 nm chip window
CHIP_CENTRE_PIXEL = 512             # PIXIS 1024 columns
MICROSCOPE_CONFIG_PATH = os.path.join(REPOSITORY_DIRECTORY, 'microscope_config.json')
MASTER_CALIBRATION_PATH = os.path.join(REPOSITORY_DIRECTORY, 'calibration',
                                       'master_calibration_microsteps_32.json')
APPROACH_STEPS = 10                 # every frame position is reached by a positive move
SINGLE_STEP_HALF_RANGE = 20
SINGLE_STEP_REVERSE_STEPS = 5
REPEATABILITY_AWAY_CENTRES_NM = (720, 920)    # the ends of the edge walk: one below, one above
REPEATABILITY_CYCLES = 3
DEFAULT_G2_CENTRES_NM = (760, 840, 920)
G2_SCAN_HALF_RANGE_STEPS = 25
G2_SCAN_STEP = 1
WIDE_SLIT_SET_UP = 'Lamp at the sample, laser off, stage 2 intermediate slit removed, ' \
                   'TRIAX slit ~500 um.'
PINHOLE_SET_UP = 'As the edge walk (halogen lamp, laser off, stage 2 intermediate slit out, ' \
                 'TRIAX slit ~500 um), plus a ~1 mm pinhole {position}; camera reading the ' \
                 'whole sensor (no ROI).'
ARGON_SET_UP = 'Ar-Hg lamp in place of the halogen, laser off, TRIAX slit ~50 um (set by hand ' \
               'first: men moves it by a relative amount).'

RUN_FILE_NAMES = {
    'edge_walk': 'stage1_edge_walk.txt',
    'single_steps': 'stage1_single_steps.txt',
    'repeatability': 'stage1_repeatability.txt',
    'axis_references': 'stage1_axis_references.txt',
    'g2_pinhole_stage2': 'stage1_g2_pinhole_stage2.txt',
    'g2_pinhole_stage1': 'stage1_g2_pinhole_stage1.txt',
}


def frame_lines(file_name):
    """Record the motor positions, name the file, take the frame."""
    return ['allmotors', f'filename {file_name}', 'acquire']


G2_FOLLOWS_G1 = 'g2 follows every g1 move (ratio from the master calibration).'
G2_MOVES_ALONE = 'g1 stays where sg puts it; g2 alone moves.'


def header_lines(title, exposure_seconds, set_up=WIDE_SLIT_SET_UP, motion=G2_FOLLOWS_G1):
    """Comment lines, the exposure if given, and 'ren' so the run log records the slit width."""
    lines = [f'# {title}',
             '# Written by python -m filter_calibration plan; procedure in '
             'docs/stage1_edge_measurement.md.',
             f'# {set_up}',
             f'# {motion}']
    if exposure_seconds is not None:
        lines += [f'acqtime {exposure_seconds}', 'nframe 1']
    return lines + ['ren']


@dataclass(frozen=True)
class ChipPlacement:
    """Where 'st' puts a wavelength on the chip, to aim the TRIAX so another lands mid-chip."""
    target_pixel: float         # spectrometer_target_pixel: where 'st' puts the wavelength
    nm_per_pixel: float         # wavelength increases with pixel

    def st_wavelength_for_chip_centre(self, centre_nm):
        return centre_nm - (CHIP_CENTRE_PIXEL - self.target_pixel) * self.nm_per_pixel


def chip_placement_from_files(config_path=MICROSCOPE_CONFIG_PATH,
                              calibration_path=MASTER_CALIBRATION_PATH):
    """The ChipPlacement this machine's config and master calibration give."""
    with open(config_path) as file:
        target_pixel = json.load(file).get('spectrometer_target_pixel', 100)
    with open(calibration_path) as file:
        nm_per_pixel = json.load(file)['wavelength_axis']['nm_per_pixel']
    return ChipPlacement(float(target_pixel), float(nm_per_pixel))


@dataclass(frozen=True)
class GratingPair:
    """How g2 follows g1 so the pair stays matched: g2 offset = round(ratio * g1 offset)."""
    g2_steps_per_g1_step: float

    def g2_offset(self, g1_offset):
        return round(self.g2_steps_per_g1_step * g1_offset)

    def move_lines(self, g1_from, g1_to):
        """Jog lines taking g1 from one offset to another, with g2 following (g1 first, so
        the edge position is reached the same way; no g2 line when it does not move)."""
        lines = [f'g1 {g1_to - g1_from}']
        g2_move = self.g2_offset(g1_to) - self.g2_offset(g1_from)
        if g2_move:
            lines.append(f'g2 {g2_move}')
        return lines


def g2_steps_per_g1_step(calibration, wavelength_nm):
    """d g2 / d g1 at a fixed wavelength, from a master calibration's wl_to_g1 and wl_to_g2."""
    g1_steps_per_nm = np.polyval(np.polyder(calibration['manual_g1']['wl_to_g1']), wavelength_nm)
    g2_steps_per_nm = np.polyval(np.polyder(calibration['manual_g2']['wl_to_g2']), wavelength_nm)
    return float(g2_steps_per_nm / g1_steps_per_nm)


def grating_pair_from_calibration(centre_nm, calibration_path=MASTER_CALIBRATION_PATH):
    """The GratingPair at one wavelength, from the master calibration."""
    with open(calibration_path) as file:
        calibration = json.load(file)
    return GratingPair(g2_steps_per_g1_step(calibration, centre_nm))


def centre_lines(centre_nm, chip_placement):
    """Put the centre wavelength mid-chip and every grating at it; log the TRIAX steps."""
    return [f'st {chip_placement.st_wavelength_for_chip_centre(centre_nm):.1f}',
            f'sg {centre_nm}', 'rg']


def edge_walk_lines(triax_centres_nm, chip_placement, grating_pair_at,
                    edge_offsets_steps=DEFAULT_EDGE_OFFSETS_STEPS, exposure_seconds=None):
    """Run file lines for the edge walk: at each centre, frames at each g1 offset (ascending,
    each reached from below), then one edge-free frame each side. grating_pair_at(centre_nm)
    gives the GratingPair by which g2 follows g1 at that centre."""
    offsets = sorted(edge_offsets_steps)
    lines = header_lines('Stage 1 edge walk: g1 offsets at each TRIAX centre', exposure_seconds)
    for centre_nm in triax_centres_nm:
        pair = grating_pair_at(centre_nm)
        lines += ['', f'# Centre {centre_nm} nm (g2 follows at {pair.g2_steps_per_g1_step:.3f} '
                      'steps per g1 step)']
        lines += centre_lines(centre_nm, chip_placement)
        lines += pair.move_lines(0, offsets[0] - APPROACH_STEPS)
        lines += pair.move_lines(offsets[0] - APPROACH_STEPS, offsets[0])
        position = offsets[0]
        for offset in offsets:
            if offset != position:
                lines += pair.move_lines(position, offset)
                position = offset
            lines += frame_lines(edge_walk_name(centre_nm, offset))
        for edge_free_offset in (EDGE_FREE_OFFSET_STEPS, -EDGE_FREE_OFFSET_STEPS):
            lines += pair.move_lines(position, edge_free_offset)
            position = edge_free_offset
            lines += frame_lines(edge_walk_name(centre_nm, edge_free_offset))
    return lines


def single_step_lines(centre_nm, chip_placement, grating_pair,
                      half_range_steps=SINGLE_STEP_HALF_RANGE,
                      reverse_steps=SINGLE_STEP_REVERSE_STEPS, exposure_seconds=None):
    """Run file lines for single g1 steps over -half_range..+half_range from below, then
    reverse_steps single steps back down, with g2 following by grating_pair. Names carry a
    sequence number, since the way back revisits positions."""
    lines = header_lines(f'Stage 1 single g1 steps at {centre_nm} nm, then back down',
                         exposure_seconds)
    lines += ['', f'# g2 follows at {grating_pair.g2_steps_per_g1_step:.3f} steps per g1 step']
    lines += centre_lines(centre_nm, chip_placement)
    lines += grating_pair.move_lines(0, -half_range_steps - APPROACH_STEPS)
    lines += grating_pair.move_lines(-half_range_steps - APPROACH_STEPS, -half_range_steps)
    position = -half_range_steps
    moves = [1] * (2 * half_range_steps) + [-1] * reverse_steps
    sequence = 0
    lines += frame_lines(single_step_name(centre_nm, sequence, position))
    for move in moves:
        lines += grating_pair.move_lines(position, position + move)
        position += move
        sequence += 1
        lines += frame_lines(single_step_name(centre_nm, sequence, position))
    return lines


def repeatability_lines(centre_nm, chip_placement, away_centres_nm=REPEATABILITY_AWAY_CENTRES_NM,
                        cycles=REPEATABILITY_CYCLES, exposure_seconds=None):
    """Run file lines for returning to one centre in different ways, one thing moved per frame.

    A start frame, then in each cycle: a frame with nothing moved; for each away centre, the
    TRIAX alone there and back, then a frame; for each away centre, the gratings alone ('sg')
    there and back, then a frame. g1 and g2 stay where 'sg' puts them (no offsets), so 'sg'
    alone sets them. 'rg' after each TRIAX return logs its steps."""
    centre_st_nm = chip_placement.st_wavelength_for_chip_centre(centre_nm)
    lines = header_lines(f'Stage 1 edge repeatability at {centre_nm} nm: one thing moved per '
                         'frame', exposure_seconds)
    lines += ['', '# Start'] + centre_lines(centre_nm, chip_placement)
    lines += frame_lines(repeatability_name(centre_nm, 0, START_VISIT))
    for cycle in range(1, cycles + 1):
        lines += ['', f'# Cycle {cycle}']
        lines += frame_lines(repeatability_name(centre_nm, cycle, STILL_VISIT))
        for away_nm in away_centres_nm:
            lines += [f'st {chip_placement.st_wavelength_for_chip_centre(away_nm):.1f}',
                      f'st {centre_st_nm:.1f}', 'rg']
            lines += frame_lines(repeatability_name(centre_nm, cycle, triax_visit(away_nm)))
        for away_nm in away_centres_nm:
            lines += [f'sg {away_nm}', f'sg {centre_nm}']
            lines += frame_lines(repeatability_name(centre_nm, cycle, gratings_visit(away_nm)))
    return lines


def axis_reference_lines(triax_centres_nm, chip_placement, exposure_seconds=None):
    """Run file lines for one Ar-Hg frame at each centre's TRIAX position (the gratings do not
    matter: the lamp light reaches the TRIAX without passing the edge, RAM-F5)."""
    lines = header_lines('Ar-Hg axis references at each centre\'s TRIAX position',
                         exposure_seconds, set_up=ARGON_SET_UP)
    for centre_nm in triax_centres_nm:
        lines += ['', f'# Centre {centre_nm} nm',
                  f'st {chip_placement.st_wavelength_for_chip_centre(centre_nm):.1f}', 'rg']
        lines += frame_lines(axis_reference_name(centre_nm))
    return lines


def g2_pinhole_scan_lines(pinhole, centres_nm, chip_placement,
                          half_range_steps=G2_SCAN_HALF_RANGE_STEPS, step=G2_SCAN_STEP,
                          exposure_seconds=None):
    """Run file lines for the g2 pinhole scan: at each centre, 'sg' there, then g2 alone from
    -half_range to +half_range in steps of `step`, each position reached from below, one frame
    at each. Ends with 'sg' at the last centre, so g2 is left matched to g1."""
    lines = header_lines(f'Stage 1 g2 pinhole scan, pinhole {PINHOLE_POSITIONS[pinhole]}',
                         exposure_seconds,
                         set_up=PINHOLE_SET_UP.format(position=PINHOLE_POSITIONS[pinhole]),
                         motion=G2_MOVES_ALONE)
    offsets = list(range(-half_range_steps, half_range_steps + 1, step))
    for centre_nm in centres_nm:
        lines += ['', f'# Centre {centre_nm} nm'] + centre_lines(centre_nm, chip_placement)
        lines += [f'g2 {offsets[0] - APPROACH_STEPS}', f'g2 {APPROACH_STEPS}']
        position = offsets[0]
        for offset in offsets:
            if offset != position:
                lines.append(f'g2 {offset - position}')
                position = offset
            lines += frame_lines(g2_pinhole_scan_name(pinhole, centre_nm, offset))
    if centres_nm:
        lines += ['', '# Leave g2 matched to g1', f'sg {centres_nm[-1]}']
    return lines


def write_run_file(lines, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as run_file:
        run_file.write('\n'.join(lines) + '\n')
    frames = sum(line == 'acquire' for line in lines)
    print(f'Wrote {path} ({frames} frames)')


def write_all_run_files(output_directory, centres_nm, single_step_centre_nm,
                        repeatability_centre_nm, repeatability_cycles, exposure_seconds,
                        axis_exposure_seconds, chip_placement=None,
                        grating_pair_at=grating_pair_from_calibration,
                        g2_centres_nm=DEFAULT_G2_CENTRES_NM,
                        g2_half_range_steps=G2_SCAN_HALF_RANGE_STEPS, g2_step=G2_SCAN_STEP,
                        g2_exposure_seconds=None):
    """Write every run file (RUN_FILE_NAMES); returns {kind: path}."""
    chip_placement = chip_placement or chip_placement_from_files()
    run_file_lines = {
        'edge_walk': edge_walk_lines(centres_nm, chip_placement, grating_pair_at,
                                     exposure_seconds=exposure_seconds),
        'single_steps': single_step_lines(single_step_centre_nm, chip_placement,
                                          grating_pair_at(single_step_centre_nm),
                                          exposure_seconds=exposure_seconds),
        'repeatability': repeatability_lines(repeatability_centre_nm, chip_placement,
                                             cycles=repeatability_cycles,
                                             exposure_seconds=exposure_seconds),
        'axis_references': axis_reference_lines(centres_nm, chip_placement,
                                                exposure_seconds=axis_exposure_seconds),
    }
    for pinhole in PINHOLE_POSITIONS:
        run_file_lines[f'g2_pinhole_{pinhole}'] = g2_pinhole_scan_lines(
            pinhole, g2_centres_nm, chip_placement, g2_half_range_steps, g2_step,
            exposure_seconds=g2_exposure_seconds)
    paths = {}
    for kind, lines in run_file_lines.items():
        paths[kind] = os.path.join(output_directory, RUN_FILE_NAMES[kind])
        write_run_file(lines, paths[kind])
    return paths

"""
Write the run files for measuring the stage 1 cutoff edge (issue #29), for the `runfile` command.

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
RAM-F5).

Three run files, written to data/runfiles/ (per machine, not tracked):
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
Every frame's file name holds its position, e.g. s1edge_t800_g1m020 (centre 800 nm, g1 at
-20 steps from 'sg 800'): saved spectra do not record grating steps, so the name is the record.
'allmotors' before each frame also puts the positions into the run log.

Bench set-up, the reasoning, and the steps by hand around these files (reference frames, the
laser-excited run): docs/stage1_edge_measurement.md.

Run:  PYTHONPATH=. python tools/make_stage1_edge_runfiles.py
      [--centres 720 760 800 840 880 920 960] [--single-step-centre 800] [--exposure 0.5]
      [--repeatability-centre 800] [--repeatability-cycles 3]
"""

import argparse
import json
import os
from dataclasses import dataclass

import numpy as np

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


def offset_label(offset_steps):
    """'p010' for +10 steps, 'm020' for -20: file names stay lower case and sign-safe."""
    return f"{'m' if offset_steps < 0 else 'p'}{abs(offset_steps):03d}"


def frame_lines(file_name):
    """Record the motor positions, name the file, take the frame."""
    return ['allmotors', f'filename {file_name}', 'acquire']


def header_lines(title, exposure_seconds):
    lines = [f'# {title}',
             '# Written by tools/make_stage1_edge_runfiles.py; procedure in '
             'docs/stage1_edge_measurement.md.',
             '# Lamp at the sample, laser off, stage 2 intermediate slit removed, '
             'TRIAX slit ~500 um.',
             '# g2 follows every g1 move (ratio from the master calibration).']
    if exposure_seconds is not None:
        lines += [f'acqtime {exposure_seconds}', 'nframe 1']
    return lines


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


def grating_pair_from_calibration(centre_nm, calibration_path=MASTER_CALIBRATION_PATH):
    """The GratingPair at one wavelength: d g2 / d g1 there, from the master calibration's
    wl_to_g1 and wl_to_g2 polynomials."""
    with open(calibration_path) as file:
        calibration = json.load(file)
    g1_steps_per_nm = np.polyval(np.polyder(calibration['manual_g1']['wl_to_g1']), centre_nm)
    g2_steps_per_nm = np.polyval(np.polyder(calibration['manual_g2']['wl_to_g2']), centre_nm)
    return GratingPair(float(g2_steps_per_nm / g1_steps_per_nm))


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
            lines += frame_lines(f's1edge_t{centre_nm}_g1{offset_label(offset)}')
        for edge_free_offset in (EDGE_FREE_OFFSET_STEPS, -EDGE_FREE_OFFSET_STEPS):
            lines += pair.move_lines(position, edge_free_offset)
            position = edge_free_offset
            lines += frame_lines(f's1edge_t{centre_nm}_g1{offset_label(edge_free_offset)}')
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
    lines += frame_lines(f's1step_t{centre_nm}_n{sequence:03d}_g1{offset_label(position)}')
    for move in moves:
        lines += grating_pair.move_lines(position, position + move)
        position += move
        sequence += 1
        lines += frame_lines(f's1step_t{centre_nm}_n{sequence:03d}_g1{offset_label(position)}')
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
    lines += frame_lines(f's1rep_t{centre_nm}_c0_start')
    for cycle in range(1, cycles + 1):
        lines += ['', f'# Cycle {cycle}']
        lines += frame_lines(f's1rep_t{centre_nm}_c{cycle}_still')
        for away_nm in away_centres_nm:
            lines += [f'st {chip_placement.st_wavelength_for_chip_centre(away_nm):.1f}',
                      f'st {centre_st_nm:.1f}', 'rg']
            lines += frame_lines(f's1rep_t{centre_nm}_c{cycle}_triax_from{away_nm}')
        for away_nm in away_centres_nm:
            lines += [f'sg {away_nm}', f'sg {centre_nm}']
            lines += frame_lines(f's1rep_t{centre_nm}_c{cycle}_gratings_from{away_nm}')
    return lines


def write_run_file(lines, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as run_file:
        run_file.write('\n'.join(lines) + '\n')
    frames = sum(line == 'acquire' for line in lines)
    print(f'Wrote {path} ({frames} frames)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--centres', type=int, nargs='+', default=DEFAULT_TRIAX_CENTRES_NM,
                        help='TRIAX centre wavelengths for the edge walk, nm')
    parser.add_argument('--single-step-centre', type=int, default=800,
                        help='TRIAX centre for the single-step run, nm')
    parser.add_argument('--repeatability-centre', type=int, default=800,
                        help='centre for the repeatability run, nm')
    parser.add_argument('--repeatability-cycles', type=int, default=REPEATABILITY_CYCLES,
                        help='cycles of the repeatability run (5 frames each, plus a start)')
    parser.add_argument('--exposure', type=float, default=None,
                        help="exposure in seconds, written as 'acqtime' at the top of each file")
    parser.add_argument('--output-directory', default=DEFAULT_OUTPUT_DIRECTORY)
    arguments = parser.parse_args(argv)
    chip_placement = chip_placement_from_files()
    write_run_file(edge_walk_lines(arguments.centres, chip_placement,
                                   grating_pair_from_calibration,
                                   exposure_seconds=arguments.exposure),
                   os.path.join(arguments.output_directory, 'stage1_edge_walk.txt'))
    write_run_file(single_step_lines(arguments.single_step_centre, chip_placement,
                                     grating_pair_from_calibration(arguments.single_step_centre),
                                     exposure_seconds=arguments.exposure),
                   os.path.join(arguments.output_directory, 'stage1_single_steps.txt'))
    write_run_file(repeatability_lines(arguments.repeatability_centre, chip_placement,
                                       cycles=arguments.repeatability_cycles,
                                       exposure_seconds=arguments.exposure),
                   os.path.join(arguments.output_directory, 'stage1_repeatability.txt'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

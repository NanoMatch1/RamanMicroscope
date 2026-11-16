"""
Write the run files for measuring the stage 1 cutoff edge (issue #29), for the `runfile` command.

What is measured: the stage 1 edge (the laser-injection mirror's cleaved edge) seen on the CCD
through a broadband lamp spectrum, as g1 turns. The edge position against g1 steps calibrates g1;
the edge width against wavelength measures how sharp the cutoff is across the range (the
collimating lens's chromatic focus shift is expected to broaden it away from one wavelength).

Two run files, written to data/runfiles/ (per machine, not tracked):
- stage1_edge_walk.txt: at each centre wavelength, the TRIAX put so that wavelength lands mid-chip
  ('st' alone puts it on spectrometer_target_pixel, near the short-wavelength end, and the
  edge would leave the chip) and 'sg' to it, then frames at g1 offsets around it (default -20
  to +20 in 10s, about +/-9 nm), each approached from below, plus one frame with g1 at +150
  steps and one at -150 (edge-free frames, one each side: open and closed, whichever way the
  edge moves).
- stage1_single_steps.txt: at one centre, g1 in single steps over -20..+20 from below, then
  back down five single steps (step uniformity, sub-step precision, backlash).
Every frame's file name holds its position, e.g. s1edge_t800_g1m020 (centre 800 nm, g1 at
-20 steps from 'sg 800'): saved spectra do not record grating steps, so the name is the record.
'allmotors' before each frame also puts the positions into the run log.

Bench set-up, the reasoning, and the steps by hand around these files (reference frames, the
laser-excited run): docs/stage1_edge_measurement.md.

Run:  PYTHONPATH=. python tools/make_stage1_edge_runfiles.py
      [--centres 720 760 800 840 880 920 960] [--single-step-centre 800] [--exposure 0.5]
"""

import argparse
import json
import os
from dataclasses import dataclass

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
             '# Lamp at the sample, laser off, stage 2 edge out, slit ~50 um.']
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


def centre_lines(centre_nm, chip_placement):
    """Put the centre wavelength mid-chip and every grating at it; log the TRIAX steps."""
    return [f'st {chip_placement.st_wavelength_for_chip_centre(centre_nm):.1f}',
            f'sg {centre_nm}', 'rg']


def edge_walk_lines(triax_centres_nm, chip_placement,
                    edge_offsets_steps=DEFAULT_EDGE_OFFSETS_STEPS, exposure_seconds=None):
    """Run file lines for the edge walk: at each centre, frames at each g1 offset (ascending,
    each reached from below), then one edge-free frame each side."""
    offsets = sorted(edge_offsets_steps)
    lines = header_lines('Stage 1 edge walk: g1 offsets at each TRIAX centre', exposure_seconds)
    for centre_nm in triax_centres_nm:
        lines += ['', f'# Centre {centre_nm} nm'] + centre_lines(centre_nm, chip_placement)
        lines += [f'g1 {offsets[0] - APPROACH_STEPS}', f'g1 {APPROACH_STEPS}']
        position = offsets[0]
        for offset in offsets:
            if offset != position:
                lines.append(f'g1 {offset - position}')
                position = offset
            lines += frame_lines(f's1edge_t{centre_nm}_g1{offset_label(offset)}')
        for edge_free_offset in (EDGE_FREE_OFFSET_STEPS, -EDGE_FREE_OFFSET_STEPS):
            lines.append(f'g1 {edge_free_offset - position}')
            position = edge_free_offset
            lines += frame_lines(f's1edge_t{centre_nm}_g1{offset_label(edge_free_offset)}')
    return lines


def single_step_lines(centre_nm, chip_placement, half_range_steps=SINGLE_STEP_HALF_RANGE,
                      reverse_steps=SINGLE_STEP_REVERSE_STEPS, exposure_seconds=None):
    """Run file lines for single g1 steps over -half_range..+half_range from below, then
    reverse_steps single steps back down. Names carry a sequence number, since the way back
    revisits positions."""
    lines = header_lines(f'Stage 1 single g1 steps at {centre_nm} nm, then back down',
                         exposure_seconds)
    lines += [''] + centre_lines(centre_nm, chip_placement)
    lines += [f'g1 {-half_range_steps - APPROACH_STEPS}', f'g1 {APPROACH_STEPS}']
    position = -half_range_steps
    moves = [1] * (2 * half_range_steps) + [-1] * reverse_steps
    sequence = 0
    lines += frame_lines(f's1step_t{centre_nm}_n{sequence:03d}_g1{offset_label(position)}')
    for move in moves:
        position += move
        sequence += 1
        lines.append(f'g1 {move}')
        lines += frame_lines(f's1step_t{centre_nm}_n{sequence:03d}_g1{offset_label(position)}')
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
    parser.add_argument('--exposure', type=float, default=None,
                        help="exposure in seconds, written as 'acqtime' at the top of each file")
    parser.add_argument('--output-directory', default=DEFAULT_OUTPUT_DIRECTORY)
    arguments = parser.parse_args(argv)
    chip_placement = chip_placement_from_files()
    write_run_file(edge_walk_lines(arguments.centres, chip_placement,
                                   exposure_seconds=arguments.exposure),
                   os.path.join(arguments.output_directory, 'stage1_edge_walk.txt'))
    write_run_file(single_step_lines(arguments.single_step_centre, chip_placement,
                                     exposure_seconds=arguments.exposure),
                   os.path.join(arguments.output_directory, 'stage1_single_steps.txt'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

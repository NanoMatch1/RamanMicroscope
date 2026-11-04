"""
Command line for the wavelength axis calibration, run from the repository root.

    python -m wavelength_calibration fit data/calibration_line_walks/linewalk_*.json
    python -m wavelength_calibration fit <files> --curvature
    python -m wavelength_calibration fit <files> --apply      # writes the master file (backed up first)

`fit` prints the report and the change from the calibration in use, and
saves it to data/calibration_fit_reports/. It only changes the master file
with --apply. The dispersion is fitted as changing with the TRIAX position
unless --fixed-dispersion is given. See docs/calibration.md section 3.
"""

import argparse
import os
import sys

from .promotion import (current_model_from_master, fit_line_walk_files, new_fit_report_path,
                        write_fit_report, write_model_to_master)
from .wavelength_axis_model import CalibrationFitError

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MASTER_PATH = os.path.join(REPOSITORY_ROOT, 'calibration', 'master_calibration_microsteps_32.json')
DEFAULT_BACKUP_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'calibration', 'backup')
DEFAULT_REPORT_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'data', 'calibration_fit_reports')


def build_argument_parser():
    parser = argparse.ArgumentParser(prog='python -m wavelength_calibration', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subcommands = parser.add_subparsers(dest='subcommand', required=True)
    fit_parser = subcommands.add_parser('fit', help='fit saved line walks and report')
    fit_parser.add_argument('line_walk_files', nargs='+')
    fit_parser.add_argument('--curvature', action='store_true', help='also fit nm_per_pixel_squared')
    fit_parser.add_argument('--triax-quadratic', action='store_true',
                            help='TRIAX wavelength quadratic in steps (with --curvature: the full physical model)')
    fit_parser.add_argument('--fixed-dispersion', action='store_true',
                            help='one nm_per_pixel for every TRIAX position (only for short walks)')
    fit_parser.add_argument('--reference-pixel', type=float, default=None,
                            help='default: keep the reference pixel of the calibration in use')
    fit_parser.add_argument('--master', default=DEFAULT_MASTER_PATH)
    fit_parser.add_argument('--backup-directory', default=DEFAULT_BACKUP_DIRECTORY)
    fit_parser.add_argument('--report-directory', default=DEFAULT_REPORT_DIRECTORY)
    fit_parser.add_argument('--apply', action='store_true', help='write the fitted model into the master file')
    return parser


def run_fit(arguments):
    current_model = current_model_from_master(arguments.master)
    reference_pixel = arguments.reference_pixel if arguments.reference_pixel is not None \
        else current_model.reference_pixel
    try:
        fit = fit_line_walk_files(arguments.line_walk_files, reference_pixel=reference_pixel,
                                  fit_dispersion_curvature=arguments.curvature,
                                  triax_polynomial_order=2 if arguments.triax_quadratic else 1,
                                  fit_dispersion_change_with_triax=not arguments.fixed_dispersion)
    except CalibrationFitError as error:
        print(f"Cannot fit: {error}")
        return 1
    report_path = new_fit_report_path(arguments.report_directory)
    backup_path = None
    if arguments.apply:
        fit.model.metadata['fit_report'] = os.path.basename(report_path)
        backup_path = write_model_to_master(fit.model, arguments.master, arguments.backup_directory)
    print(write_fit_report(report_path, fit, current_model, arguments.line_walk_files,
                           master_path=arguments.master, backup_path=backup_path), end='')
    if not arguments.apply:
        print("Not applied (use --apply to write it to the master calibration).")
    print(f"Report saved to {report_path}")
    return 0


def main(argument_list=None):
    arguments = build_argument_parser().parse_args(argument_list)
    if arguments.subcommand == 'fit':
        return run_fit(arguments)
    return 1


if __name__ == '__main__':
    sys.exit(main())

"""
Command line for the stage 1 calibrations (g1 against the edge, then g2 through a pinhole), run
from the repository root.

    python -m filter_calibration plan --exposure 15 --axis-exposure 15
        writes the run files to data/runfiles/ (see run_files.py): the edge session's four, and
        the two g2 pinhole scans
    python -m filter_calibration fit data/runfile_logs/stage1_*_20261201_*.txt
        analyses the edge session those run logs recorded (here, every stage 1 run of
        2026-12-01): report, results.json and plots in
        data/filter_calibration_reports/stage1_edge_<time>/
    python -m filter_calibration fit <logs> --apply
        also writes the proposed g1 and g2 entries into the master calibration (backed up first),
        and refuses if a gate check fails
    python -m filter_calibration fit-g2 data/runfile_logs/stage1_g2_pinhole_*_20261202_*.txt
        analyses g2 pinhole scans (taken after the g1 calibration was applied): the g2 offset,
        in data/filter_calibration_reports/stage1_g2_<time>/; --apply writes it to manual_g2

`fit` and `fit-g2` save their plots unless --no-plots is given (for headless runs). They expand
wildcards themselves (the Windows command prompt does not), and find the frames under
--data-directory (default data/) by the names in the logs. Pass every run log of the session,
and only that session's (older runs have the same frame names): the walk gives the
calibration, the axis references correct it, and the single steps and the repeatability run
are checked against it. Re-running the command in a report gives the same result from the same
files; results.json records each file's SHA-256.
"""

import argparse
import json
import os
import sys

from wavelength_calibration.calibration_checks import any_failed
from wavelength_calibration.file_arguments import expand_file_arguments

from .analysis import AnalysisSettings, analyse_session
from .calibration_checks import run_edge_checks
from .g2_analysis import analyse_g2_session
from .g2_checks import run_g2_checks
from .g2_plots import save_g2_plots
from .g2_report import write_g2_report
from .plots import save_all_plots
from .promotion import apply_g2_offset, apply_proposed_calibration
from .report import (REPOSITORY_ROOT, command_line_text, new_report_directory, provenance,
                     write_report)
from .run_files import (DEFAULT_G2_CENTRES_NM, DEFAULT_OUTPUT_DIRECTORY, DEFAULT_TRIAX_CENTRES_NM,
                        G2_SCAN_HALF_RANGE_STEPS, G2_SCAN_STEP, REPEATABILITY_CYCLES,
                        write_all_run_files)
from .session import read_session

DEFAULT_DATA_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'data')
DEFAULT_MASTER_PATH = os.path.join(REPOSITORY_ROOT, 'calibration',
                                   'master_calibration_microsteps_32.json')
DEFAULT_BACKUP_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'calibration', 'backup')
DEFAULT_REPORT_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'data', 'filter_calibration_reports')


def build_argument_parser():
    parser = argparse.ArgumentParser(prog='python -m filter_calibration', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subcommands = parser.add_subparsers(dest='subcommand', required=True)

    plan = subcommands.add_parser('plan', help='write the run files')
    plan.add_argument('--centres', type=int, nargs='+', default=DEFAULT_TRIAX_CENTRES_NM,
                      help='TRIAX centre wavelengths for the edge walk and axis references, nm')
    plan.add_argument('--single-step-centre', type=int, default=800)
    plan.add_argument('--repeatability-centre', type=int, default=800)
    plan.add_argument('--repeatability-cycles', type=int, default=REPEATABILITY_CYCLES,
                      help='5 frames each, plus a start frame')
    plan.add_argument('--exposure', type=float, default=None,
                      help="halogen frames' exposure in seconds ('acqtime' at the top)")
    plan.add_argument('--axis-exposure', type=float, default=None,
                      help="Ar-Hg frames' exposure in seconds")
    plan.add_argument('--g2-centres', type=int, nargs='+', default=DEFAULT_G2_CENTRES_NM,
                      help='centre wavelengths of the g2 pinhole scans, nm')
    plan.add_argument('--g2-half-range', type=int, default=G2_SCAN_HALF_RANGE_STEPS,
                      help='g2 pinhole scans run from -this to +this g2 steps around sg')
    plan.add_argument('--g2-step', type=int, default=G2_SCAN_STEP)
    plan.add_argument('--g2-exposure', type=float, default=None,
                      help="g2 pinhole frames' exposure in seconds (the pinhole passes less "
                           'light than the edge walk gets)')
    plan.add_argument('--output-directory', default=DEFAULT_OUTPUT_DIRECTORY)

    fit = subcommands.add_parser('fit', help='analyse a session from its run logs')
    fit.add_argument('run_logs', nargs='+')
    fit.add_argument('--data-directory', default=DEFAULT_DATA_DIRECTORY)
    fit.add_argument('--order', type=int, default=2, help='calibration polynomial order')
    fit.add_argument('--master', default=DEFAULT_MASTER_PATH)
    fit.add_argument('--backup-directory', default=DEFAULT_BACKUP_DIRECTORY)
    fit.add_argument('--report-directory', default=DEFAULT_REPORT_DIRECTORY)
    fit.add_argument('--no-plots', action='store_true',
                     help='skip the plots (they are made by default), for headless runs')
    fit.add_argument('--apply', action='store_true',
                     help='write the proposed g1/g2 entries into the master calibration')

    fit_g2 = subcommands.add_parser('fit-g2', help='analyse g2 pinhole scans from their run logs')
    fit_g2.add_argument('run_logs', nargs='+')
    for option, default in (('--data-directory', DEFAULT_DATA_DIRECTORY),
                            ('--master', DEFAULT_MASTER_PATH),
                            ('--backup-directory', DEFAULT_BACKUP_DIRECTORY),
                            ('--report-directory', DEFAULT_REPORT_DIRECTORY)):
        fit_g2.add_argument(option, default=default)
    fit_g2.add_argument('--no-plots', action='store_true',
                        help='skip the plot (made by default), for headless runs')
    fit_g2.add_argument('--apply', action='store_true',
                        help='write the g2 offset into manual_g2 of the master calibration')
    return parser


def run_plan(arguments):
    write_all_run_files(arguments.output_directory, arguments.centres,
                        arguments.single_step_centre, arguments.repeatability_centre,
                        arguments.repeatability_cycles, arguments.exposure,
                        arguments.axis_exposure, g2_centres_nm=arguments.g2_centres,
                        g2_half_range_steps=arguments.g2_half_range, g2_step=arguments.g2_step,
                        g2_exposure_seconds=arguments.g2_exposure)
    return 0


def run_fit(arguments):
    run_logs = expand_file_arguments(arguments.run_logs)
    if not run_logs:
        print(f'No run logs match {arguments.run_logs}.')
        return 1
    found = read_session(run_logs, arguments.data_directory)
    with open(arguments.master) as master_file:
        master = json.load(master_file)
    session_analysis = analyse_session(found, master,
                                       AnalysisSettings(calibration_order=arguments.order))
    check_results = run_edge_checks(session_analysis)
    report_directory = new_report_directory(arguments.report_directory)
    provenance_record = provenance(session_analysis, command_line_text(), arguments.master)
    applied = None
    if arguments.apply:
        if any_failed(check_results) or session_analysis.proposed is None:
            print('Not applied: a gate check failed or there is no calibration to apply.')
        else:
            applied = apply_proposed_calibration(session_analysis.proposed, arguments.master,
                                                 arguments.backup_directory, report_directory)
    print(write_report(report_directory, session_analysis, check_results, provenance_record,
                       applied), end='')
    if not arguments.no_plots:
        for path in save_all_plots(session_analysis, report_directory):
            print(f'Plot: {path}')
    if not arguments.apply:
        print('Not applied (use --apply to write it to the master calibration).')
    print(f'Report: {report_directory}')
    return 0 if session_analysis.calibration is not None else 1


def run_fit_g2(arguments):
    run_logs = expand_file_arguments(arguments.run_logs)
    if not run_logs:
        print(f'No run logs match {arguments.run_logs}.')
        return 1
    found = read_session(run_logs, arguments.data_directory)
    with open(arguments.master) as master_file:
        master = json.load(master_file)
    session_analysis = analyse_g2_session(found, master)
    check_results = run_g2_checks(session_analysis)
    report_directory = new_report_directory(arguments.report_directory, prefix='stage1_g2')
    provenance_record = provenance(session_analysis, command_line_text(), arguments.master)
    applied = None
    if arguments.apply:
        if any_failed(check_results) or session_analysis.proposed is None:
            print('Not applied: a gate check failed or there is no offset to apply.')
        else:
            applied = apply_g2_offset(session_analysis.proposed, arguments.master,
                                      arguments.backup_directory, report_directory)
    print(write_g2_report(report_directory, session_analysis, check_results, provenance_record,
                          applied), end='')
    if not arguments.no_plots:
        for path in save_g2_plots(session_analysis, report_directory):
            print(f'Plot: {path}')
    if not arguments.apply:
        print('Not applied (use --apply to write it to the master calibration).')
    print(f'Report: {report_directory}')
    return 0 if session_analysis.proposed is not None else 1


SUBCOMMANDS = {'plan': run_plan, 'fit': run_fit, 'fit-g2': run_fit_g2}


def main(argument_list=None):
    arguments = build_argument_parser().parse_args(argument_list)
    return SUBCOMMANDS[arguments.subcommand](arguments)


if __name__ == '__main__':
    sys.exit(main())

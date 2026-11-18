"""
Command line for the stage 1 edge (g1) calibration, run from the repository root.

    python -m filter_calibration plan --exposure 15 --axis-exposure 15
        writes the four run files to data/runfiles/ (see run_files.py)
    python -m filter_calibration fit data/runfile_logs/stage1_*_20261201_*.txt
        analyses the session those run logs recorded (here, every stage 1 run of 2026-12-01):
        report, results.json and plots in data/filter_calibration_reports/stage1_edge_<time>/
    python -m filter_calibration fit <logs> --apply
        also writes the proposed g1 and g2 entries into the master calibration (backed up first),
        and refuses if a gate check fails

`fit` expands wildcards itself (the Windows command prompt does not), and finds the frames under
--data-directory (default data/) by the names in the logs. Pass every run log of the session,
and only that session's (older runs have the same frame names): the walk gives the calibration, the axis references correct it,
and the single steps and the repeatability run are checked against it. Re-running the command
in a report gives the same result from the same files; results.json records each file's SHA-256.
"""

import argparse
import glob
import json
import os
import sys

from wavelength_calibration.calibration_checks import any_failed

from .analysis import AnalysisSettings, analyse_session
from .calibration_checks import run_edge_checks
from .plots import save_all_plots
from .promotion import apply_proposed_calibration
from .report import (REPOSITORY_ROOT, command_line_text, new_report_directory, provenance,
                     write_report)
from .run_files import (DEFAULT_OUTPUT_DIRECTORY, DEFAULT_TRIAX_CENTRES_NM, REPEATABILITY_CYCLES,
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
    plan.add_argument('--output-directory', default=DEFAULT_OUTPUT_DIRECTORY)

    fit = subcommands.add_parser('fit', help='analyse a session from its run logs')
    fit.add_argument('run_logs', nargs='+')
    fit.add_argument('--data-directory', default=DEFAULT_DATA_DIRECTORY)
    fit.add_argument('--order', type=int, default=2, help='calibration polynomial order')
    fit.add_argument('--master', default=DEFAULT_MASTER_PATH)
    fit.add_argument('--backup-directory', default=DEFAULT_BACKUP_DIRECTORY)
    fit.add_argument('--report-directory', default=DEFAULT_REPORT_DIRECTORY)
    fit.add_argument('--no-plots', action='store_true')
    fit.add_argument('--apply', action='store_true',
                     help='write the proposed g1/g2 entries into the master calibration')
    return parser


def run_plan(arguments):
    write_all_run_files(arguments.output_directory, arguments.centres,
                        arguments.single_step_centre, arguments.repeatability_centre,
                        arguments.repeatability_cycles, arguments.exposure,
                        arguments.axis_exposure)
    return 0


def expand_run_log_arguments(arguments):
    """Each argument as typed, or the files its wildcard matches, in order, without repeats."""
    paths = []
    for argument in arguments:
        matches = sorted(glob.glob(argument)) if glob.has_magic(argument) else [argument]
        paths += [path for path in matches if path not in paths]
    return paths


def run_fit(arguments):
    run_logs = expand_run_log_arguments(arguments.run_logs)
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


def main(argument_list=None):
    arguments = build_argument_parser().parse_args(argument_list)
    if arguments.subcommand == 'plan':
        return run_plan(arguments)
    return run_fit(arguments)


if __name__ == '__main__':
    sys.exit(main())

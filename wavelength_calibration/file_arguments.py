"""
File arguments for the calibration command lines.

A Unix shell expands a wildcard such as linewalk_*.json before the program sees it; the
Windows command prompt passes it through unchanged. So each calibration command line
(wavelength_calibration, filter_calibration) expands its own file arguments with
expand_file_arguments, and the same command works on both.
"""

import glob


def expand_file_arguments(arguments):
    """Each argument as typed, or the files its wildcard matches (sorted), in order, without
    repeats. A wildcard that matches nothing contributes nothing."""
    paths = []
    for argument in arguments:
        matches = sorted(glob.glob(argument)) if glob.has_magic(argument) else [argument]
        paths += [path for path in matches if path not in paths]
    return paths

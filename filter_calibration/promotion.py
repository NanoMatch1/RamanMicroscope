"""
Write a session's proposed g1 (and g2) entries into the master calibration: only when asked, and
only if no gate check fails.

As with the wavelength axis calibration, promotion is a separate, explicit step: the analysis
writes a report, and a person decides. The master file is backed up first
(wavelength_calibration.promotion.back_up_master), and only manual_g1 (g1_to_wl, wl_to_g1) and
manual_g2 (wl_to_g2, g2_to_wl) change.

The master file's loader reads every entry of a group as a calibration, so the record of what
was applied, when and from which report cannot live there. It goes in a history file beside it
(HISTORY_FILE_NAME, e.g. calibration/stage1_edge_calibration_history.json): a list, appended to
on every apply, holding the report folder, the software commit, and the old and new entries.
"""

import datetime
import json
import os

from wavelength_calibration.promotion import back_up_master
from wavelength_calibration.provenance import software_version

from .report import REPOSITORY_ROOT

HISTORY_FILE_NAME = 'stage1_edge_calibration_history.json'


def apply_proposed_calibration(proposed, master_path, backup_directory, report_directory):
    """Back up the master file, write the proposed entries, append to the history beside it.
    Returns {'master_path', 'backup_path', 'history_path', 'applied_at'}."""
    history_path = os.path.join(os.path.dirname(os.path.abspath(master_path)), HISTORY_FILE_NAME)
    with open(master_path) as master_file:
        master = json.load(master_file)
    previous = {'manual_g1': dict(master['manual_g1']), 'manual_g2': dict(master['manual_g2'])}
    backup_path = back_up_master(master_path, backup_directory)
    master['manual_g1']['g1_to_wl'] = list(proposed.g1_to_wl)
    master['manual_g1']['wl_to_g1'] = list(proposed.wl_to_g1)
    master['manual_g2']['wl_to_g2'] = list(proposed.wl_to_g2)
    master['manual_g2']['g2_to_wl'] = list(proposed.g2_to_wl)
    with open(master_path, 'w') as master_file:
        json.dump(master, master_file, indent=4)

    applied_at = datetime.datetime.now().isoformat(timespec='seconds')
    history = []
    if os.path.exists(history_path):
        with open(history_path) as history_file:
            history = json.load(history_file)
    history.append({
        'applied_at': applied_at,
        'report_directory': report_directory,
        'software': software_version(REPOSITORY_ROOT),
        'valid_wavelength_range_nm': list(proposed.wavelength_range_nm),
        'previous': previous,
        'applied': {'manual_g1': master['manual_g1'], 'manual_g2': master['manual_g2']},
    })
    with open(history_path, 'w') as history_file:
        json.dump(history, history_file, indent=2)
    return {'master_path': master_path, 'backup_path': backup_path,
            'history_path': history_path, 'applied_at': applied_at}

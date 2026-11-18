"""
Write a session's proposed entries into the master calibration: only when asked, and only if no
gate check fails.

- An edge session (apply_proposed_calibration) writes manual_g1 (g1_to_wl, wl_to_g1) and
  manual_g2 (wl_to_g2, g2_to_wl), g2 moved with g1 at the master's pairing.
- A g2 pinhole session (apply_g2_offset) writes manual_g2 only: wl_to_g2 shifted by the
  measured offset and g2_to_wl to match.

As with the wavelength axis calibration, promotion is a separate, explicit step: the analysis
writes a report, and a person decides. The master file is backed up first
(wavelength_calibration.promotion.back_up_master).

The master file's loader reads every entry of a group as a calibration, so the record of what
was applied, when and from which report cannot live there. It goes in a history file beside it
(HISTORY_FILE_NAME, e.g. calibration/stage1_edge_calibration_history.json): a list, appended to
on every apply, holding what kind of session it was, the report folder, the software commit,
and the old and new entries.
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
    history_path = _history_path(master_path)
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

    applied_at = _append_history(history_path, {
        'kind': 'stage1 edge (g1, g2 following)',
        'report_directory': report_directory,
        'valid_wavelength_range_nm': list(proposed.wavelength_range_nm),
        'previous': previous,
        'applied': {'manual_g1': master['manual_g1'], 'manual_g2': master['manual_g2']},
    })
    return {'master_path': master_path, 'backup_path': backup_path,
            'history_path': history_path, 'applied_at': applied_at}


def apply_g2_offset(proposed, master_path, backup_directory, report_directory):
    """Back up the master file, write the shifted manual_g2 entries, append to the history.
    Returns {'master_path', 'backup_path', 'history_path', 'applied_at'}."""
    history_path = _history_path(master_path)
    with open(master_path) as master_file:
        master = json.load(master_file)
    previous = {'manual_g2': dict(master['manual_g2'])}
    backup_path = back_up_master(master_path, backup_directory)
    master['manual_g2']['wl_to_g2'] = list(proposed.wl_to_g2)
    master['manual_g2']['g2_to_wl'] = list(proposed.g2_to_wl)
    with open(master_path, 'w') as master_file:
        json.dump(master, master_file, indent=4)
    applied_at = _append_history(history_path, {
        'kind': f'g2 pinhole ({proposed.pinhole})',
        'report_directory': report_directory,
        'g2_offset_steps': proposed.offset_steps,
        'centres_nm': list(proposed.centres_nm),
        'previous': previous,
        'applied': {'manual_g2': master['manual_g2']},
    })
    return {'master_path': master_path, 'backup_path': backup_path,
            'history_path': history_path, 'applied_at': applied_at}


def _history_path(master_path):
    return os.path.join(os.path.dirname(os.path.abspath(master_path)), HISTORY_FILE_NAME)


def _append_history(history_path, entry):
    """Append one entry (with the time and software added) to the history; returns the time."""
    applied_at = datetime.datetime.now().isoformat(timespec='seconds')
    history = []
    if os.path.exists(history_path):
        with open(history_path) as history_file:
            history = json.load(history_file)
    history.append({'applied_at': applied_at, 'software': software_version(REPOSITORY_ROOT),
                    **entry})
    with open(history_path, 'w') as history_file:
        json.dump(history, history_file, indent=2)
    return applied_at

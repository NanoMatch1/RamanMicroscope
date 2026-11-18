"""
The report of a g2 pinhole session: what was measured, the offset it gives, and how to get it
again.

Each analysis writes a folder, data/filter_calibration_reports/stage1_g2_<time>/, holding
- report.txt: the gate checks, the proposed g2 entries against the master, every scan (centre,
  offset, window, g1:g2 mismatch, band rows per step and target row), and every frame's light;
- results.json: the same numbers, for scripts and for comparing sessions;
- g2_pinhole.png (g2_plots.py);
and the same provenance as the edge report (report.provenance): software, command line, time,
every run log and frame with its SHA-256, and the master calibration's SHA-256.
"""

import json
import os

import numpy as np

from wavelength_calibration.calibration_checks import format_check_report

from .report import _format_polynomial, _optional, _plain


def scan_rows(session_analysis):
    rows = []
    for scan in session_analysis.scans:
        fit = scan.total_fit
        rows.append({
            'pinhole': scan.pinhole, 'centre_nm': scan.centre_nm, 'frames': len(scan.records),
            'g1_counts': scan.g1_counts, 'master_g1_count': scan.master_g1_count,
            'centre_count': scan.centre_count, 'centre_uncertainty': scan.centre_uncertainty,
            'master_count': scan.master_count, 'offset_steps': scan.offset_steps,
            'window_width_steps': fit.width_steps if fit else None,
            'window_sigma_steps': fit.sigma_steps if fit else None,
            'window_residual_fraction': fit.residual_fraction if fit else None,
            'all_light_centre_count': fit.centre_count if fit else None,
            'mismatch_steps_per_nm': scan.mismatch_steps_per_nm,
            'rows_per_g2_step': scan.rows_per_g2_step,
            'target_band_row': scan.target_band_row,
            'block_centres': [
                {'wavelength_nm': wavelength,
                 'centre_count': block.centre_count if block else None,
                 'centre_uncertainty': block.centre_uncertainty if block else None}
                for wavelength, block in zip(scan.light.block_wavelengths_nm, scan.block_fits)]
            if scan.light else [],
            'triax_steps': scan.triax_steps, 'slit_width_um': scan.slit_width_um,
        })
    return rows


def frame_rows(session_analysis):
    rows = []
    for scan in session_analysis.scans:
        light = scan.light.total_light if scan.light is not None else [None] * len(scan.records)
        for record, frame_light in zip(scan.records, light):
            rows.append({
                'name': record.name, 'index': record.index, 'acquired_at': record.acquired_at,
                'g1_count': record.g1_count, 'g2_count': record.g2_count,
                'triax_steps': record.triax_steps, 'slit_width_um': record.slit_width_um,
                'frame_path': record.frame_path,
                'light': float(frame_light) if frame_light is not None else None,
                'band_row': scan.band_track.row(record.g2_count)
                if scan.band_track is not None else None})
    return rows


def results_dictionary(session_analysis, check_results, provenance_record, applied=None):
    return {
        'format': 'stage1_g2_pinhole/1',
        'provenance': provenance_record,
        'gate_checks': [_plain(result) for result in check_results],
        'reference_pinhole': session_analysis.reference_pinhole,
        'proposed_master_entries': _plain(session_analysis.proposed),
        'master_entries_in_use': _plain(session_analysis.master),
        'scans': scan_rows(session_analysis),
        'frames': frame_rows(session_analysis),
        'applied': applied,
    }


def report_lines(session_analysis, check_results, provenance_record, applied=None):
    software = provenance_record['software']
    lines = ['Stage 1 g2 pointing (pinhole scan), filter_calibration',
             f"analysed {provenance_record['analysed_at']}, software {software['commit']} "
             f"({software['branch']}, uncommitted changes: {software['uncommitted_changes']})",
             f"command: {provenance_record['command_line']}",
             f"run logs: {', '.join(provenance_record['run_logs'])}",
             f"frames: {len(provenance_record['frames'])} files (SHA-256 in results.json)", '']
    lines += format_check_report(check_results) + ['']

    proposed = session_analysis.proposed
    if proposed is not None:
        master = session_analysis.master
        lines += [f'proposed g2 offset {proposed.offset_steps:+.2f} +/- '
                  f'{proposed.offset_uncertainty:.2f} steps (weighted mean of the pinhole '
                  f'{proposed.pinhole} scans at {proposed.centres_nm} nm, spread '
                  f'{proposed.spread_steps:.2f}), added to wl_to_g2:',
                  f"  manual_g2.wl_to_g2  {_format_polynomial(proposed.wl_to_g2)}",
                  f"            in use  {_format_polynomial(master['manual_g2']['wl_to_g2'])}",
                  f"  manual_g2.g2_to_wl  {_format_polynomial(proposed.g2_to_wl)}",
                  f"            in use  {_format_polynomial(master['manual_g2']['g2_to_wl'])}"]
    if applied:
        lines += [f"APPLIED to {applied['master_path']} (previous file backed up to "
                  f"{applied['backup_path']})"]
    lines += ['', 'pinhole  centre  frames  g2 centre (+/-)   in use     offset  window w/sigma  '
                  'resid  mismatch st/nm  rows/step  target row']
    for row in scan_rows(session_analysis):
        window = (f"{row['window_width_steps']:.1f}/{row['window_sigma_steps']:.1f}"
                  if row['window_width_steps'] is not None else '-')
        uncertainty = _optional(row['centre_uncertainty'], '.2f')
        lines.append(
            f"{row['pinhole']:7s}  {row['centre_nm']:6d}  {row['frames']:6d}  "
            f"{_optional(row['centre_count'], '.2f'):>9s} ({uncertainty:>4s})  "
            f"{_optional(row['master_count'], '.2f'):>9s}  "
            f"{_optional(row['offset_steps'], '+.2f'):>7s}  {window:>14s}  "
            f"{_optional(row['window_residual_fraction'], '.3f'):>5s}  "
            f"{_optional(row['mismatch_steps_per_nm'], '+.4f'):>15s}  "
            f"{_optional(row['rows_per_g2_step'], '+.2f'):>9s}  "
            f"{_optional(row['target_band_row'], '.1f'):>10s}")
        for block in row['block_centres']:
            lines.append(f"{'':17s}block {block['wavelength_nm']:.1f} nm: centre "
                         f"{_optional(block['centre_count'], '.2f')} +/- "
                         f"{_optional(block['centre_uncertainty'], '.2f')}")
    lines += ['', 'frames: name, g1, g2, TRIAX, slit, light, band row']
    for row in frame_rows(session_analysis):
        lines.append(
            f"  {row['name']:30s} {_optional(row['g1_count'], 'd'):>5s} "
            f"{_optional(row['g2_count'], 'd'):>5s} {_optional(row['triax_steps'], 'd'):>7s} "
            f"{_optional(row['slit_width_um'], '.0f'):>4s} {_optional(row['light'], '.0f'):>10s} "
            f"{_optional(row['band_row'], '.1f'):>6s}")
    return lines


def write_g2_report(directory, session_analysis, check_results, provenance_record,
                    applied=None):
    """report.txt and results.json in the directory; returns the report text."""
    text = '\n'.join(report_lines(session_analysis, check_results, provenance_record,
                                  applied)) + '\n'
    with open(os.path.join(directory, 'report.txt'), 'w') as report_file:
        report_file.write(text)
    with open(os.path.join(directory, 'results.json'), 'w') as results_file:
        json.dump(results_dictionary(session_analysis, check_results, provenance_record,
                                     applied), results_file, indent=1,
                  default=lambda value: value.item() if isinstance(value, np.generic) else None)
    return text

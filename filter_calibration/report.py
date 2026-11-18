"""
The report of a stage 1 edge session: what was measured, what it gives, and how to get it again.

Each analysis writes a folder, data/filter_calibration_reports/<time>/, holding
- report.txt: the gate checks, the proposed calibration against the master, every centre, the
  single steps, the repeatability, the axis references and every frame's edge;
- results.json: the same numbers, for scripts and for comparing sessions;
- the plots (plots.py);
and, inside both, the provenance: the software (commit, branch, uncommitted changes), the
command line that made it, the time, every run log and frame file with its SHA-256, and the
master calibration file's SHA-256. The command line re-runs the analysis; the hashes say
whether the inputs are still the ones it used.
"""

import datetime
import hashlib
import json
import os
import platform
import sys
from dataclasses import asdict, is_dataclass

import numpy as np

from wavelength_calibration.calibration_checks import format_check_report
from wavelength_calibration.provenance import software_version

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def new_report_directory(parent_directory, now=None, prefix='stage1_edge'):
    now = now or datetime.datetime.now()
    directory = os.path.join(parent_directory, now.strftime(f'{prefix}_%Y%m%d_%H%M%S'))
    os.makedirs(directory, exist_ok=True)
    return directory


def provenance(session_analysis, command_line, master_path):
    """Where the result came from: software, inputs (with hashes), time. Reads the analysis's
    frames_found and settings, which the edge and the g2 analyses both have."""
    import scipy
    records = session_analysis.frames_found.records
    return {
        'analysed_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'command_line': command_line,
        'software': software_version(REPOSITORY_ROOT),
        'python': platform.python_version(),
        'numpy': np.__version__,
        'scipy': scipy.__version__,
        'run_logs': {path: file_sha256(path)
                     for path in session_analysis.frames_found.run_log_paths},
        'frames': {record.frame_path: file_sha256(record.frame_path)
                   for record in records if record.frame_path},
        'master_calibration': {'path': master_path,
                               'sha256': file_sha256(master_path) if master_path else None},
        'settings': _plain(session_analysis.settings),
    }


def _plain(value):
    """JSON-ready copy: dataclasses to dicts, numpy to Python, arrays dropped."""
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()
                if not isinstance(item, np.ndarray)}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def frame_rows(session_analysis):
    rows = []
    for frame in session_analysis.frames:
        record, edge = frame.record, frame.edge
        rows.append({
            'name': record.name, 'index': record.index, 'kind': record.frame_name.kind,
            'acquired_at': record.acquired_at, 'g1_count': record.g1_count,
            'g2_count': record.g2_count, 'triax_steps': record.triax_steps,
            'slit_width_um': record.slit_width_um, 'exposure_s': frame.exposure_s,
            'frame_path': record.frame_path,
            'edge_nm': edge.edge_nm if edge else None,
            'edge_uncertainty_nm': edge.edge_uncertainty_nm if edge else None,
            'axis_correction_nm': frame.axis_correction_nm,
            'corrected_edge_nm': frame.corrected_edge_nm,
            'width_nm': edge.width_nm if edge else None,
            'plateau': edge.plateau if edge else None,
            'residual_fraction': edge.residual_fraction if edge else None,
            'band_row': frame.result.band_row_at_centre if frame.result else None,
            'saturated_pixels_in_band': frame.result.saturated_pixels_in_band
            if frame.result else None,
            'background': frame.result.background if frame.result else None,
        })
    return rows


def results_dictionary(session_analysis, check_results, provenance_record, applied=None):
    reference_rows = {}
    for centre, reference in session_analysis.axis_references.items():
        reference_rows[centre] = _plain(reference)
    return {
        'format': 'stage1_edge_calibration/1',
        'provenance': provenance_record,
        'gate_checks': [_plain(result) for result in check_results],
        'calibration_fit': _plain(session_analysis.calibration),
        'proposed_master_entries': _plain(session_analysis.proposed),
        'master_entries_in_use': _plain(session_analysis.master),
        'centres': [_plain(summary) for summary in session_analysis.centres],
        'single_steps': _plain(session_analysis.single_steps),
        'repeatability': _plain(session_analysis.repeatability),
        'axis_references': reference_rows,
        'frames': frame_rows(session_analysis),
        'applied': applied,
    }


def _format_polynomial(coefficients):
    return '[' + ', '.join(f'{value:.10g}' for value in coefficients) + ']'


def report_lines(session_analysis, check_results, provenance_record, applied=None):
    software = provenance_record['software']
    lines = ['Stage 1 edge calibration (g1), filter_calibration',
             f"analysed {provenance_record['analysed_at']}, software {software['commit']} "
             f"({software['branch']}, uncommitted changes: {software['uncommitted_changes']})",
             f"command: {provenance_record['command_line']}",
             f"run logs: {', '.join(provenance_record['run_logs'])}",
             f"frames: {len(provenance_record['frames'])} files (SHA-256 in results.json)", '']
    lines += format_check_report(check_results) + ['']

    fit = session_analysis.calibration
    proposed = session_analysis.proposed
    if fit is not None:
        lines += [f'g1 calibration (edge at the sg wavelength): edge = polynomial in the g1 count, '
                  f'order {len(fit.coefficients) - 1}, over {len(fit.residuals)} walk frames, '
                  f'residual {fit.residual_rms:.3f} nm rms']
    if proposed is not None:
        master = session_analysis.master
        lines += ['proposed master entries (valid over '
                  f'{proposed.wavelength_range_nm[0]:.1f}-'
                  f'{proposed.wavelength_range_nm[1]:.1f} nm; '
                  'outside it they extrapolate):',
                  f"  manual_g1.g1_to_wl  {_format_polynomial(proposed.g1_to_wl)}",
                  f"            in use  {_format_polynomial(master['manual_g1']['g1_to_wl'])}",
                  f"  manual_g1.wl_to_g1  {_format_polynomial(proposed.wl_to_g1)}",
                  f"            in use  {_format_polynomial(master['manual_g1']['wl_to_g1'])}",
                  f"  manual_g2.wl_to_g2  {_format_polynomial(proposed.wl_to_g2)}  (g2 moved with "
                  f"g1 at the master's pairing; fit within "
                  f"{proposed.g2_fit_residual_steps:.2f} steps)",
                  f"            in use  {_format_polynomial(master['manual_g2']['wl_to_g2'])}",
                  f"  manual_g2.g2_to_wl  {_format_polynomial(proposed.g2_to_wl)}",
                  f"            in use  {_format_polynomial(master['manual_g2']['g2_to_wl'])}"]
    if applied:
        lines += [f"APPLIED to {applied['master_path']} (previous file backed up to "
                  f"{applied['backup_path']})"]
    lines += ['', 'centre  frames  slope nm/step       rms   width nm      band rows/step  axis '
                  'corr  master g1  edge there  g1 for edge at centre (shift)']
    for summary in session_analysis.centres:
        shift = (f'{summary.count_for_edge_at_centre:9.1f} '
                 f'({summary.count_for_edge_at_centre - summary.master_count:+.1f})'
                 if summary.count_for_edge_at_centre is not None else '')
        lines.append(
            f'{summary.centre_nm:6d}  {summary.frames:6d}  {summary.slope_nm_per_step:+.4f} '
            f'+/- {summary.slope_uncertainty:.4f}  {summary.residual_rms_nm:.3f}  '
            f'{summary.width_mean_nm:.2f} +/- {summary.width_spread_nm:.2f}  '
            f'{summary.band_rows_per_g1_step:+.3f}          '
            f'{_optional(summary.axis_correction_nm, "+.3f"):>9s}  '
            f'{_optional(summary.master_count, ".1f"):>9s}  '
            f'{_optional(summary.edge_at_master_count_nm, ".2f"):>10s}  {shift}')

    steps = session_analysis.single_steps
    if steps is not None:
        sizes = np.abs(steps.step_sizes_nm)
        lines += ['', f'single steps at {steps.centre_nm} nm: '
                      f'{steps.slope_nm_per_step:+.4f} nm/step, residual '
                      f'{steps.residual_rms_nm:.3f} nm rms (max {steps.residual_max_nm:.3f});'
                      f' step sizes mean {np.mean(sizes):.3f}, std {np.std(sizes):.3f}, '
                      f'{sizes.min():.3f}-{sizes.max():.3f} nm',
                  '  way back down, minus the way-up line (nm): '
                  + ' '.join(f'{value:+.3f}' for value in steps.reverse_offsets_nm)
                  + (f'  -> backlash {steps.backlash_steps:.2f} steps'
                     if steps.backlash_steps is not None else ''),
                  f'  against the walk fit: {_optional(steps.offset_from_walk_nm, "+.3f")} nm']
    repeatability = session_analysis.repeatability
    if repeatability is not None:
        lines += ['', f'repeatability at {repeatability.centre_nm} nm (corrected edge, nm):']
        for visit_kind, entries in repeatability.edges_by_visit_kind.items():
            values = ' '.join(f'{edge:.3f}' for _, edge in entries)
            spread = repeatability.spread_nm(visit_kind)
            lines.append(f'  {visit_kind:9s} {values}' +
                         (f'   spread {spread:.3f}' if spread is not None else ''))
        lines.append(f'  against the walk fit: '
                     f'{_optional(repeatability.offset_from_walk_nm, "+.3f")} nm')
    if session_analysis.axis_references:
        lines += ['', 'axis references (Ar-Hg, band rows): correction, spread, lines used']
        for centre, reference in sorted(session_analysis.axis_references.items()):
            used = ', '.join(f'{line.nist_nm:.1f}' for line in reference.lines_used)
            lines.append(f'  {centre} nm: {_optional(reference.correction_nm, "+.3f")} nm, '
                         f'{_optional(reference.spread_nm, ".3f")} nm; '
                         f'TRIAX {reference.triax_steps}, '
                         f'slit {reference.slit_width_um} um; {used}')
    lines += ['', 'frames: name, g1, g2, TRIAX, slit, edge (frame axis), correction, width, '
                  'plateau, band row, background']
    for row in frame_rows(session_analysis):
        lines.append(
            f"  {row['name']:34s} {_optional(row['g1_count'], 'd'):>5s} "
            f"{_optional(row['g2_count'], 'd'):>5s} {_optional(row['triax_steps'], 'd'):>7s} "
            f"{_optional(row['slit_width_um'], '.0f'):>4s} {_optional(row['edge_nm'], '.3f'):>8s} "
            f"{_optional(row['axis_correction_nm'], '+.3f'):>7s} "
            f"{_optional(row['width_nm'], '.2f'):>5s} {_optional(row['plateau'], '.0f'):>8s} "
            f"{_optional(row['band_row'], '.1f'):>6s} {row['background'] or ''}")
    return lines


def _optional(value, format_spec):
    return '-' if value is None else format(value, format_spec)


def write_report(directory, session_analysis, check_results, provenance_record, applied=None):
    """report.txt and results.json in the directory; returns the report text."""
    text = '\n'.join(report_lines(session_analysis, check_results, provenance_record,
                                  applied)) + '\n'
    with open(os.path.join(directory, 'report.txt'), 'w') as report_file:
        report_file.write(text)
    with open(os.path.join(directory, 'results.json'), 'w') as results_file:
        json.dump(results_dictionary(session_analysis, check_results, provenance_record,
                                     applied), results_file, indent=1)
    return text


def command_line_text():
    return ' '.join([os.path.basename(sys.executable), '-m', 'filter_calibration'] + sys.argv[1:])

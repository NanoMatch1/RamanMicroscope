"""Stage 1 edge position and width, 2026-11-18 rerun (intermediate slit out, TRIAX slit 500 um,
g2 following g1, 15 s frames).

Background. The frames carry a diffuse stray-light background with no edge in it (lamp light
reaching the wide TRIAX slit outside the filter), which drifts by up to ~40 counts per pixel over
a walk (stray_light_and_band_profile.py). It is removed in two steps:
1. subtract the closed frame (g1 at -150) taken at the same centre: removes the background's
   shape along the wavelength axis and down the rows (reference frames, which have no closed
   frame at their slit width, skip this step);
2. subtract, column by column, the median of rows 15-30 rows either side of the band: removes
   what is left (the drift, and light the band itself scatters).
The band is thin (6-12 rows FWHM) and slants (+0.25 rows/nm), so each column sums the rows
within BAND_HALF_HEIGHT_ROWS of the band's centre line, fitted per frame.

Edge model, in pixels: (a + b (x - x0)) * Phi((x - x0) / s) + c, Phi the normal CDF; light passes
on the long-wavelength side. x0 is the edge midpoint (where a symmetric blur leaves it), 2.355 s
its width as an equivalent Gaussian FWHM. Fitted over a window
from FIT_BLUE_NM below to FIT_RED_NM above a first guess (steepest rise of the smoothed band).

Also fitted per row across the band (rows centre +/- 4), to see whether the edge slants across
the rows (light entering stage 1 at different angles in its dispersion plane).

Reports:
- every frame: edge (nm), width (nm), fit residual, band light;
- edge walk: edge against g1 at each centre (slope nm/step, edge at g1 = 0 minus the centre);
- single steps at 800 nm: slope, residuals, way back down (backlash);
- slit series and check pair;
- the effect of the stray light: the edge with step 2 only (no closed-frame subtraction).

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/fit_edges.py
"""
import glob
import json
import os
import re

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.optimize import curve_fit
from scipy.special import ndtr

import exploration_paths

DATA_DIRECTORY = exploration_paths.DATA_DIRECTORY
OUTPUT_DIRECTORY = exploration_paths.OUTPUT_DIRECTORY
OUTPUT_PATH = os.path.join(OUTPUT_DIRECTORY, 'fit_edges.txt')
RESULTS_PATH = os.path.join(OUTPUT_DIRECTORY, 'fit_edges.json')
CENTRES = (720, 760, 800, 840, 880, 920, 960)
SATURATION_LEVEL = 65535
BAND_SEARCH_ROWS = (550, 660)
BAND_HALF_HEIGHT_ROWS = 10
FLANK_ROWS = (15, 30)
PER_ROW_OFFSETS = tuple(range(-4, 5))
SMOOTHING_COLUMNS = 9
FIT_BLUE_NM = 10.0
FIT_RED_NM = 15.0
MINIMUM_EDGE_SIGNAL = 2000.0
WALK_PATTERN = re.compile(r's1edge_t(\d+)_g1([mp])(\d+)')
STEP_PATTERN = re.compile(r's1step_t800_n(\d+)_g1([mp])(\d+)')

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def load_frame(path):
    frame = np.load(path, allow_pickle=False)
    metadata = json.loads(str(frame['metadata']))
    return frame['image'].astype(float), frame['wavelength'], metadata


def frame_path(name, index=0):
    group = name.split('_')[0]
    return os.path.join(DATA_DIRECTORY, group, name, f'{name}_{index:06d}.npz')


def signed_offset(sign_letter, digits):
    return (-1 if sign_letter == 'm' else 1) * int(digits)


def band_centre_line(image):
    """Centre row of the band against column: a line fitted to per-column centroids where the
    band is bright. Returns (slope rows/column, intercept) or None if there is no band."""
    rows = np.arange(*BAND_SEARCH_ROWS)
    region = image[BAND_SEARCH_ROWS[0]:BAND_SEARCH_ROWS[1]]
    columns, centres, weights = [], [], []
    for column in range(5, image.shape[1] - 5, 10):
        profile = region[:, column - 5:column + 5].mean(axis=1)
        profile = profile - np.median(profile)
        peak = int(np.argmax(profile))
        if profile[peak] < 300:
            continue
        window = slice(max(peak - 6, 0), peak + 7)
        positive = np.clip(profile[window], 0, None)
        columns.append(column)
        centres.append(np.sum(rows[window] * positive) / positive.sum())
        weights.append(profile[peak])
    if len(columns) < 5:
        return None
    return np.polyfit(columns, centres, 1, w=np.sqrt(weights))


def remove_flank_background(image, centre_rows):
    """Subtract, per column, the median of the rows FLANK_ROWS either side of the band."""
    cleaned = image.copy()
    row_index = np.arange(image.shape[0])[:, None]
    distance = np.abs(row_index - centre_rows[None, :])
    flank = (distance >= FLANK_ROWS[0]) & (distance <= FLANK_ROWS[1])
    flank_values = np.where(flank, image, np.nan)
    cleaned -= np.nanmedian(flank_values, axis=0)[None, :]
    return cleaned


def band_rows_sum(image, centre_rows, half_height, offset=0):
    row_index = np.arange(image.shape[0])[:, None]
    distance = row_index - (centre_rows[None, :] + offset)
    inside = np.abs(distance) <= half_height
    return np.where(inside, image, 0.0).sum(axis=0)


def edge_model(pixel, amplitude, slope, edge_pixel, width_pixels, baseline):
    return (amplitude + slope * (pixel - edge_pixel)) * ndtr((pixel - edge_pixel) / width_pixels) \
        + baseline


def fit_edge(signal, wavelength):
    """Fit the edge model; returns dict with edge_nm, width_nm (FWHM equivalent), residual, or
    None if there is no edge to fit."""
    pixels = np.arange(len(signal), dtype=float)
    smoothed = uniform_filter1d(signal, SMOOTHING_COLUMNS)
    if np.percentile(smoothed, 98) < MINIMUM_EDGE_SIGNAL:
        return None
    derivative = np.gradient(smoothed)
    guess_pixel = int(np.argmax(derivative[10:-10])) + 10
    nm_per_pixel = abs(np.gradient(wavelength)[guess_pixel])
    first = max(0, int(guess_pixel - FIT_BLUE_NM / nm_per_pixel))
    last = min(len(signal), int(guess_pixel + FIT_RED_NM / nm_per_pixel))
    window = slice(first, last)
    plateau = float(np.median(signal[guess_pixel + 20:last])) if last > guess_pixel + 25 \
        else float(signal[last - 1])
    try:
        parameters, covariance = curve_fit(
            edge_model, pixels[window], signal[window],
            p0=[plateau, 0.0, guess_pixel, 10.0, float(np.median(signal[first:guess_pixel - 20]))
                if guess_pixel - first > 25 else 0.0],
            maxfev=20000)
    except (RuntimeError, ValueError):
        return None
    amplitude, slope, edge_pixel, width_pixels, baseline = parameters
    if not (first < edge_pixel < last) or amplitude <= 0:
        return None
    residual = signal[window] - edge_model(pixels[window], *parameters)
    return {
        'edge_nm': float(np.interp(edge_pixel, pixels, wavelength)),
        'edge_pixel': float(edge_pixel),
        'edge_uncertainty_nm': float(np.sqrt(covariance[2, 2]) * nm_per_pixel),
        'width_nm': float(2.3548 * abs(width_pixels) * nm_per_pixel),
        'residual_fraction': float(np.std(residual) / amplitude),
        'plateau': float(amplitude),
        'window_reaches_chip_end': first == 0 or last == len(signal),
    }


def analyse_frame(path, closed_image=None):
    image, wavelength, metadata = load_frame(path)
    saturated = int((image >= SATURATION_LEVEL).sum())
    background_removed = image - closed_image if closed_image is not None else image
    line = band_centre_line(background_removed if closed_image is not None
                            else remove_flank_background(image, np.full(image.shape[1], 600.0)))
    if line is None:
        return {'saturated': saturated, 'no_band': True}
    centre_rows = np.polyval(line, np.arange(image.shape[1]))
    cleaned = remove_flank_background(background_removed, centre_rows)
    signal = band_rows_sum(cleaned, centre_rows, BAND_HALF_HEIGHT_ROWS)
    result = {'saturated': saturated, 'no_band': False,
              'band_row_at_centre': float(centre_rows[512]),
              'band_rows_per_nm': float(line[0] / abs(np.gradient(wavelength)[512])),
              'exposure_s': metadata['_current_parameters'].get('acquisition_time'),
              'slit_um': metadata['_current_parameters'].get('spec_slit_width')}
    result['summed'] = fit_edge(signal, wavelength)
    result['per_row'] = {offset: fit_edge(band_rows_sum(cleaned, centre_rows, 0.5, offset),
                                          wavelength)
                         for offset in PER_ROW_OFFSETS}
    if closed_image is not None:
        flank_only = remove_flank_background(image, centre_rows)
        result['flank_background_only'] = fit_edge(
            band_rows_sum(flank_only, centre_rows, BAND_HALF_HEIGHT_ROWS), wavelength)
    return result


def describe(name, result):
    if result.get('no_band'):
        return f'{name:34s} no band found (saturated {result["saturated"]})'
    fit = result['summed']
    if fit is None:
        return f'{name:34s} band but no edge fitted (saturated {result["saturated"]})'
    per_row = [result['per_row'][offset] for offset in PER_ROW_OFFSETS]
    per_row_text = ' '.join(f'{row_fit["edge_nm"] - fit["edge_nm"]:+5.2f}' if row_fit else '  -  '
                            for row_fit in per_row)
    flags = []
    if result['saturated']:
        flags.append(f'sat {result["saturated"]}')
    if fit['window_reaches_chip_end']:
        flags.append('window at chip end')
    return (f'{name:34s} {fit["edge_nm"]:8.3f} +/- {fit["edge_uncertainty_nm"]:.3f}  '
            f'w {fit["width_nm"]:5.2f}  res {fit["residual_fraction"]:.3f}  '
            f'plateau {fit["plateau"] / 1e3:6.0f}k  row {result["band_row_at_centre"]:6.1f}  '
            f'rows-minus-sum [{per_row_text}]  {" ".join(flags)}')


def line_fit(offsets, edges):
    slope, intercept = np.polyfit(offsets, edges, 1)
    residual = edges - np.polyval((slope, intercept), offsets)
    return slope, intercept, residual


def main():
    results = {}
    report('Edge (nm) +/- fit error, width (FWHM-equivalent nm), residual / plateau, plateau '
           '(band counts per column), band centre row at column 512,')
    report('and the per-row edges minus the summed edge for rows centre -4 ... +4.')

    report('\n== Edge walk ==')
    walk = {}
    for centre in CENTRES:
        closed_image, _, _ = load_frame(frame_path(f's1edge_t{centre}_g1m150'))
        for path in sorted(glob.glob(os.path.join(DATA_DIRECTORY, 's1edge',
                                                  f's1edge_t{centre}_*', '*.npz'))):
            name = os.path.basename(path)[:-4]
            match = WALK_PATTERN.match(name)
            offset = signed_offset(match.group(2), match.group(3))
            result = analyse_frame(path, None if offset == -150 else closed_image)
            if offset == -150:
                result = analyse_frame(path)
            results[name] = result
            walk[(centre, offset)] = result
            report(describe(name, result))

    report('\nEdge against g1 at each centre (g1 = -20 ... +20, approached from below)')
    for centre in CENTRES:
        points = [(offset, walk[(centre, offset)]['summed']['edge_nm'])
                  for offset in (-20, -10, 0, 10, 20)
                  if walk[(centre, offset)].get('summed')]
        if len(points) < 3:
            report(f'  {centre} nm: only {len(points)} edges')
            continue
        offsets, edges = (np.array(values, dtype=float) for values in zip(*points))
        slope, intercept, residual = line_fit(offsets, edges)
        widths = [walk[(centre, offset)]['summed']['width_nm'] for offset, _ in points]
        report(f'  {centre} nm: {slope:+.4f} nm/step over {len(points)} frames, edge at g1 = 0: '
               f'{intercept:.2f} nm ({intercept - centre:+.2f} from the centre), residual rms '
               f'{np.std(residual):.3f} nm, widths {np.mean(widths):.2f} +/- {np.std(widths):.2f}')

    report('\n== Single steps at 800 nm ==')
    steps = []
    for path in sorted(glob.glob(os.path.join(DATA_DIRECTORY, 's1step', '*', '*.npz'))):
        name = os.path.basename(path)[:-4]
        match = STEP_PATTERN.match(name)
        result = analyse_frame(path, load_frame(frame_path('s1edge_t800_g1m150'))[0])
        results[name] = result
        report(describe(name, result))
        if result.get('summed'):
            steps.append((int(match.group(1)), signed_offset(match.group(2), match.group(3)),
                          result['summed']['edge_nm'], result['summed']['width_nm']))
    sequences, offsets, edges, widths = (np.array(values, dtype=float) for values in zip(*steps))
    way_up = sequences <= 40
    slope, intercept, residual = line_fit(offsets[way_up], edges[way_up])
    report(f'\nWay up: {slope:+.4f} nm/step over {way_up.sum()} steps, residual rms '
           f'{np.std(residual):.3f} nm, max {np.max(np.abs(residual)):.3f} nm; '
           f'width {np.mean(widths[way_up]):.2f} +/- {np.std(widths[way_up]):.2f} nm')
    report('Residuals on the way up (g1: edge minus line, nm):')
    report('  ' + ' '.join(f'{int(offset):+d}:{value:+.2f}'
                           for offset, value in zip(offsets[way_up], residual)))
    step_sizes = np.diff(edges[way_up])
    report(f'Single-step edge moves: mean {np.mean(step_sizes):+.3f}, '
           f'std {np.std(step_sizes):.3f}, '
           f'min {np.min(step_sizes):+.3f}, max {np.max(step_sizes):+.3f} nm')
    report('Way back down (g1: edge minus the way-up line, nm): '
           + ' '.join(f'{int(offset):+d}:{edge - np.polyval((slope, intercept), offset):+.2f}'
                      for offset, edge in zip(offsets[~way_up], edges[~way_up])))

    report('\n== Reference frames (no closed frame at these slit widths: flank background only) ==')
    for path in sorted(glob.glob(os.path.join(DATA_DIRECTORY, 's1ref', 's1ref_*', '*.npz'))):
        name = os.path.basename(path)[:-4]
        if 'arhg' in name or 'dark' in name:
            continue
        result = analyse_frame(path)
        results[name] = result
        report(describe(name, result) + f'  exp {result.get("exposure_s")} s')

    report('\n== Stray light: edge with the closed frame subtracted minus edge with flank '
           'background only (nm) ==')
    differences = [result['summed']['edge_nm'] - result['flank_background_only']['edge_nm']
                   for result in results.values()
                   if result.get('summed') and result.get('flank_background_only')]
    report(f'  over {len(differences)} frames: mean {np.mean(differences):+.4f}, std '
           f'{np.std(differences):.4f}, max |diff| {np.max(np.abs(differences)):.4f}')

    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')
    with open(RESULTS_PATH, 'w') as output:
        json.dump(results, output, indent=1, default=str)


if __name__ == '__main__':
    main()

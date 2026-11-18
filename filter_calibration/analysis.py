"""
A stage 1 edge session analysed: every frame's edge, the axis corrections, the g1 calibration
fit, and the statistics the gate checks and the report read.

The g1 calibration puts the edge AT the 'sg' wavelength: g1_to_wl(count) is the wavelength on
the edge at that g1 count, fitted to the edge walk (a polynomial in the absolute g1 count, as
the master calibration stores it), and wl_to_g1 its inverse, fitted the other way round. The
laser spot sits a fixed g1 angle from the edge, so the offset for laser work is one constant in
counts, set afterwards with 'referencegratings' (lab-notebook RAM-F5).

g2 keeps following g1. On 2026-11-18, with g2 moved by the master calibration's ratio d g2 / d g1
at each centre, the band moved only 0.045 rows per g1 step: the master pairing is right to about
1-1.5 % (RAM-F5). So the proposed g2 keeps that pairing: at each wavelength it moves by the same
ratio times the change in g1, wl_to_g2_new = wl_to_g2 + ratio * (wl_to_g1_new - wl_to_g1).

Every edge is read on the axis saved with its frame and corrected by the Ar-Hg axis reference
taken at the same TRIAX position, when the session has one (axis_reference.py).

Frames are loaded through `frame_loader`, so tests can hand in frames without files.
"""

from dataclasses import dataclass, field

import numpy as np

from .axis_reference import AxisReferenceSettings, measure_axis_reference
from .edge_fit import EdgeFitSettings, analyse_edge_frame
from .frame_names import AXIS_REFERENCE, EDGE_WALK, REFERENCE, REPEATABILITY, SINGLE_STEP
from .run_files import g2_steps_per_g1_step
from .session import load_frame

TRIAX_MATCH_TOLERANCE_STEPS = 5     # an axis reference applies to frames this close in TRIAX steps
CLOSED_FRAME_MAXIMUM_LIGHT_FRACTION = 0.3   # of the open frame's band light, to count as closed


@dataclass(frozen=True)
class AnalysisSettings:
    calibration_order: int = 2
    edge: EdgeFitSettings = EdgeFitSettings()
    axis: AxisReferenceSettings = AxisReferenceSettings()


@dataclass
class FrameAnalysis:
    record: object                      # session.FrameRecord
    result: object = None               # edge_fit.FrameEdgeResult (None for axis/dark frames)
    axis_correction_nm: float = None    # from the axis reference at this TRIAX position
    exposure_s: float = None

    @property
    def edge(self):
        return self.result.edge if self.result is not None else None

    @property
    def corrected_edge_nm(self):
        """The edge on the corrected axis (uncorrected if there is no axis reference)."""
        if self.edge is None:
            return None
        return self.edge.edge_nm + (self.axis_correction_nm or 0.0)


@dataclass
class PolynomialFit:
    coefficients: list                  # highest power first (numpy.polyfit, the master format)
    x_values: list
    y_values: list
    residuals: list
    labels: list                        # frame names

    @property
    def residual_rms(self):
        return float(np.sqrt(np.mean(np.square(self.residuals)))) if self.residuals else None

    def __call__(self, x):
        return np.polyval(self.coefficients, x)


@dataclass
class CentreSummary:
    centre_nm: int
    frames: int
    slope_nm_per_step: float = None
    slope_uncertainty: float = None
    residual_rms_nm: float = None
    width_mean_nm: float = None
    width_spread_nm: float = None
    band_rows_per_g1_step: float = None     # g2 tracking: the band's row against g1
    triax_steps: int = None
    axis_correction_nm: float = None
    master_count: float = None              # where the master calibration's sg puts g1
    edge_at_master_count_nm: float = None   # the fitted edge there
    count_for_edge_at_centre: float = None  # where the new calibration puts g1


@dataclass
class SingleStepStatistics:
    centre_nm: int
    slope_nm_per_step: float
    residual_rms_nm: float
    residual_max_nm: float
    step_sizes_nm: list
    reverse_offsets_nm: list            # way back down, minus the way-up line
    offset_from_walk_nm: float          # mean way-up residual against the walk's calibration

    @property
    def backlash_steps(self):
        if not self.reverse_offsets_nm:
            return None
        return float(np.mean(np.abs(self.reverse_offsets_nm)) / abs(self.slope_nm_per_step))


@dataclass
class RepeatabilityStatistics:
    centre_nm: int
    edges_by_visit_kind: dict           # 'start'/'still'/'triax'/'gratings' -> [(name, edge)]
    offset_from_walk_nm: float          # mean of all, against the walk's calibration

    def spread_nm(self, visit_kind):
        edges = [edge for _, edge in self.edges_by_visit_kind.get(visit_kind, [])]
        return float(np.ptp(edges)) if len(edges) > 1 else None

    def standard_deviation_nm(self, visit_kind):
        edges = [edge for _, edge in self.edges_by_visit_kind.get(visit_kind, [])]
        return float(np.std(edges, ddof=1)) if len(edges) > 1 else None


@dataclass
class ProposedCalibration:
    """The master calibration entries this session proposes, and the range they rest on."""
    g1_to_wl: list
    wl_to_g1: list
    g2_to_wl: list
    wl_to_g2: list
    wavelength_range_nm: tuple
    g2_fit_residual_steps: float


@dataclass
class SessionAnalysis:
    settings: AnalysisSettings
    frames_found: object                # session.FramesFound
    frames: list = field(default_factory=list)      # FrameAnalysis
    axis_references: dict = field(default_factory=dict)     # centre -> AxisReference
    calibration: PolynomialFit = None
    centres: list = field(default_factory=list)     # CentreSummary
    single_steps: SingleStepStatistics = None
    repeatability: RepeatabilityStatistics = None
    proposed: ProposedCalibration = None
    master: dict = field(default_factory=dict)      # the master's manual_g1 and manual_g2

    def frames_of_kind(self, kind):
        return [frame for frame in self.frames if frame.record.frame_name.kind == kind]

    def walk_frames_with_edges(self):
        return [frame for frame in self.frames_of_kind(EDGE_WALK)
                if not frame.record.frame_name.is_edge_free and frame.edge is not None
                and frame.record.g1_count is not None]


def _exposure_seconds(frame):
    return frame.metadata.get('_current_parameters', {}).get('acquisition_time')


def _band_light(frame):
    """How bright the band is: the 99.9th percentile above the median (the band is thin)."""
    return float(np.percentile(frame.image, 99.9) - np.median(frame.image))


def _closed_frames_by_centre(records, frame_loader):
    """{centre: loaded Frame} of each centre's closed frame: the darker of its two edge-free
    walk frames, if it really is dark. When the edge does not move with g1 (the intermediate
    slit left in), both look alike, and subtracting one would remove the band itself."""
    closed = {}
    by_centre = {}
    for record in records:
        if record.frame_name.kind == EDGE_WALK and record.frame_name.is_edge_free and \
                record.frame_path:
            by_centre.setdefault(record.frame_name.centre_nm, []).append(record)
    for centre, centre_records in by_centre.items():
        loaded = sorted((frame_loader(record.frame_path) for record in centre_records),
                        key=_band_light)
        if len(loaded) == 2 and _band_light(loaded[0]) < \
                CLOSED_FRAME_MAXIMUM_LIGHT_FRACTION * _band_light(loaded[1]):
            closed[centre] = loaded[0]
    return closed


def _fit_polynomial(x_values, y_values, labels, order):
    coefficients = np.polyfit(x_values, y_values, order)
    residuals = np.asarray(y_values) - np.polyval(coefficients, x_values)
    return PolynomialFit(coefficients=[float(value) for value in coefficients],
                         x_values=[float(value) for value in x_values],
                         y_values=[float(value) for value in y_values],
                         residuals=[float(value) for value in residuals], labels=list(labels))


def _count_where(polynomial, wavelength_nm, near_count):
    """The real root of polynomial(count) = wavelength nearest near_count."""
    roots = np.roots(np.polysub(polynomial, [wavelength_nm]))
    real_roots = [root.real for root in roots if abs(root.imag) < 1e-9]
    if not real_roots:
        return None
    return float(min(real_roots, key=lambda root: abs(root - near_count)))


def _line_with_uncertainty(x_values, y_values):
    if len(x_values) < 3:
        return None, None, None
    coefficients, covariance = np.polyfit(x_values, y_values, 1, cov=True)
    residuals = np.asarray(y_values) - np.polyval(coefficients, x_values)
    return coefficients, float(np.sqrt(covariance[0, 0])), \
        float(np.sqrt(np.mean(residuals ** 2)))


def analyse_frames(found, settings, frame_loader):
    """FrameAnalysis for every record with a file: edges, then the axis references."""
    closed_frames = _closed_frames_by_centre(found.records, frame_loader)
    frames = []
    for record in found.records:
        frame_name = record.frame_name
        analysis = FrameAnalysis(record=record)
        frames.append(analysis)
        if record.frame_path is None or frame_name.kind == AXIS_REFERENCE:
            continue
        if frame_name.kind == REFERENCE and ('dark' in frame_name.name or
                                             'arhg' in frame_name.name):
            continue
        if frame_name.is_edge_free:     # open or closed: there is no edge in it to fit
            continue
        frame = frame_loader(record.frame_path)
        analysis.exposure_s = _exposure_seconds(frame)
        closed = closed_frames.get(frame_name.centre_nm)
        use_closed = closed is not None and frame_name.kind != REFERENCE and \
            _exposure_seconds(closed) == analysis.exposure_s and \
            closed.image.shape == frame.image.shape
        analysis.result = analyse_edge_frame(frame.image, frame.wavelength_nm,
                                             closed.image if use_closed else None, settings.edge)
    return frames


def measure_axis_references(frames, settings, frame_loader):
    """{centre: AxisReference} from the axis frames, each measured in that centre's band rows."""
    band_rows_by_centre = {}
    for frame in frames:
        if frame.result is not None and frame.result.band_found and \
                frame.record.frame_name.kind in (EDGE_WALK, SINGLE_STEP, REPEATABILITY):
            band_rows_by_centre.setdefault(frame.record.frame_name.centre_nm, []).append(
                frame.result.band_row_at_centre)
    all_band_rows = [row for rows in band_rows_by_centre.values() for row in rows]
    references = {}
    for frame in frames:
        record = frame.record
        if record.frame_name.kind != AXIS_REFERENCE or record.frame_path is None:
            continue
        centre = record.frame_name.centre_nm
        band_rows = band_rows_by_centre.get(centre) or all_band_rows
        if not band_rows:
            continue
        loaded = frame_loader(record.frame_path)
        frame.exposure_s = _exposure_seconds(loaded)
        reference = measure_axis_reference(loaded.image, loaded.wavelength_nm,
                                           float(np.median(band_rows)), settings.axis)
        reference.triax_steps = record.triax_steps
        reference.slit_width_um = record.slit_width_um
        references[centre] = reference
    return references


def apply_axis_corrections(frames, axis_references):
    """Give each frame the correction of the axis reference at its TRIAX position (by TRIAX
    steps when both are logged, else by centre)."""
    for frame in frames:
        record = frame.record
        if frame.edge is None:
            continue
        for centre, reference in axis_references.items():
            if reference.correction_nm is None:
                continue
            if record.triax_steps is not None and reference.triax_steps is not None:
                matches = abs(record.triax_steps - reference.triax_steps) <= \
                    TRIAX_MATCH_TOLERANCE_STEPS
            else:
                matches = record.frame_name.centre_nm == centre
            if matches:
                frame.axis_correction_nm = reference.correction_nm
                break


def fit_g1_calibration(session_analysis):
    """The edge against the absolute g1 count over the edge walk, and the inverse fit."""
    walk = session_analysis.walk_frames_with_edges()
    order = session_analysis.settings.calibration_order
    if len(walk) <= order + 1:
        return None, None
    counts = [frame.record.g1_count for frame in walk]
    edges = [frame.corrected_edge_nm for frame in walk]
    labels = [frame.record.name for frame in walk]
    return _fit_polynomial(counts, edges, labels, order), \
        _fit_polynomial(edges, counts, labels, order)


def summarise_centres(session_analysis, inverse_fit):
    master_wl_to_g1 = session_analysis.master.get('manual_g1', {}).get('wl_to_g1')
    summaries = []
    walk = session_analysis.walk_frames_with_edges()
    for centre in sorted({frame.record.frame_name.centre_nm for frame in walk}):
        centre_frames = [frame for frame in walk if frame.record.frame_name.centre_nm == centre]
        offsets = [frame.record.frame_name.g1_offset_steps for frame in centre_frames]
        edges = [frame.corrected_edge_nm for frame in centre_frames]
        widths = [frame.edge.width_nm for frame in centre_frames]
        band_rows = [frame.result.band_row_at_centre for frame in centre_frames]
        line, slope_uncertainty, residual_rms = _line_with_uncertainty(offsets, edges)
        row_line, _, _ = _line_with_uncertainty(offsets, band_rows)
        summary = CentreSummary(
            centre_nm=centre, frames=len(centre_frames),
            slope_nm_per_step=float(line[0]) if line is not None else None,
            slope_uncertainty=slope_uncertainty, residual_rms_nm=residual_rms,
            width_mean_nm=float(np.mean(widths)), width_spread_nm=float(np.std(widths)),
            band_rows_per_g1_step=float(row_line[0]) if row_line is not None else None,
            triax_steps=centre_frames[0].record.triax_steps,
            axis_correction_nm=centre_frames[0].axis_correction_nm)
        if master_wl_to_g1 is not None and session_analysis.calibration is not None:
            summary.master_count = float(np.polyval(master_wl_to_g1, centre))
            summary.edge_at_master_count_nm = float(session_analysis.calibration(
                summary.master_count))
            summary.count_for_edge_at_centre = _count_where(
                session_analysis.calibration.coefficients, centre, summary.master_count)
        summaries.append(summary)
    return summaries


def single_step_statistics(session_analysis):
    steps = [frame for frame in session_analysis.frames_of_kind(SINGLE_STEP)
             if frame.edge is not None]
    if len(steps) < 4:
        return None
    steps.sort(key=lambda frame: frame.record.frame_name.sequence)
    offsets = [frame.record.frame_name.g1_offset_steps for frame in steps]
    turn = int(np.argmax(offsets))
    way_up, way_down = steps[:turn + 1], steps[turn + 1:]
    up_offsets = np.array(offsets[:turn + 1], dtype=float)
    up_edges = np.array([frame.corrected_edge_nm for frame in way_up])
    line = np.polyfit(up_offsets, up_edges, 1)
    residuals = up_edges - np.polyval(line, up_offsets)
    calibration = session_analysis.calibration
    walk_offsets = [frame.corrected_edge_nm - calibration(frame.record.g1_count)
                    for frame in way_up if frame.record.g1_count is not None] \
        if calibration is not None else []
    return SingleStepStatistics(
        centre_nm=steps[0].record.frame_name.centre_nm,
        slope_nm_per_step=float(line[0]),
        residual_rms_nm=float(np.sqrt(np.mean(residuals ** 2))),
        residual_max_nm=float(np.max(np.abs(residuals))),
        step_sizes_nm=[float(value) for value in np.diff(up_edges)],
        reverse_offsets_nm=[float(frame.corrected_edge_nm - np.polyval(
            line, frame.record.frame_name.g1_offset_steps)) for frame in way_down],
        offset_from_walk_nm=float(np.mean(walk_offsets)) if walk_offsets else None)


def repeatability_statistics(session_analysis):
    visits = [frame for frame in session_analysis.frames_of_kind(REPEATABILITY)
              if frame.edge is not None]
    if not visits:
        return None
    edges_by_kind = {}
    for frame in visits:
        edges_by_kind.setdefault(frame.record.frame_name.visit_kind, []).append(
            (frame.record.name, frame.corrected_edge_nm))
    calibration = session_analysis.calibration
    walk_offsets = [frame.corrected_edge_nm - calibration(frame.record.g1_count)
                    for frame in visits if frame.record.g1_count is not None] \
        if calibration is not None else []
    return RepeatabilityStatistics(
        centre_nm=visits[0].record.frame_name.centre_nm, edges_by_visit_kind=edges_by_kind,
        offset_from_walk_nm=float(np.mean(walk_offsets)) if walk_offsets else None)


def propose_calibration(session_analysis, inverse_fit):
    """New g1 entries from the walk; g2 moved with g1 at the master's pairing ratio."""
    master = session_analysis.master
    calibration = session_analysis.calibration
    if calibration is None or inverse_fit is None or 'manual_g2' not in master:
        return None
    edges = calibration.y_values
    wavelength_range = (float(min(edges)), float(max(edges)))
    wavelengths = np.linspace(*wavelength_range, 50)
    old_g1 = np.polyval(master['manual_g1']['wl_to_g1'], wavelengths)
    new_g1 = np.polyval(inverse_fit.coefficients, wavelengths)
    ratios = np.array([g2_steps_per_g1_step(master, wavelength) for wavelength in wavelengths])
    new_g2 = np.polyval(master['manual_g2']['wl_to_g2'], wavelengths) + ratios * (new_g1 - old_g1)
    order = session_analysis.settings.calibration_order
    wl_to_g2 = np.polyfit(wavelengths, new_g2, order)
    g2_to_wl = np.polyfit(new_g2, wavelengths, order)
    residual = new_g2 - np.polyval(wl_to_g2, wavelengths)
    return ProposedCalibration(
        g1_to_wl=list(calibration.coefficients), wl_to_g1=list(inverse_fit.coefficients),
        g2_to_wl=[float(value) for value in g2_to_wl],
        wl_to_g2=[float(value) for value in wl_to_g2],
        wavelength_range_nm=wavelength_range,
        g2_fit_residual_steps=float(np.max(np.abs(residual))))


def analyse_session(frames_found, master_calibration, settings=AnalysisSettings(),
                    frame_loader=load_frame):
    """SessionAnalysis of a session read by session.read_session."""
    session_analysis = SessionAnalysis(
        settings=settings, frames_found=frames_found,
        master={key: master_calibration[key] for key in ('manual_g1', 'manual_g2')
                if key in master_calibration})
    session_analysis.frames = analyse_frames(frames_found, settings, frame_loader)
    session_analysis.axis_references = measure_axis_references(session_analysis.frames, settings,
                                                               frame_loader)
    apply_axis_corrections(session_analysis.frames, session_analysis.axis_references)
    session_analysis.calibration, inverse_fit = fit_g1_calibration(session_analysis)
    session_analysis.centres = summarise_centres(session_analysis, inverse_fit)
    session_analysis.single_steps = single_step_statistics(session_analysis)
    session_analysis.repeatability = repeatability_statistics(session_analysis)
    session_analysis.proposed = propose_calibration(session_analysis, inverse_fit)
    return session_analysis

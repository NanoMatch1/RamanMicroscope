"""
A g2 pinhole session analysed: at each centre wavelength, the g2 count that points the beam
through the pinhole's centre, how far that is from the calibration in use, and the band's
target row.

Convention, as for g1: the calibration is about the 'sg' wavelength. 'sg <centre>' puts g1's
edge at the centre wavelength, to within the rounding of g1 to a whole count; the reference
wavelength of a scan is where the calibration in use puts the edge at the logged g1 count,
g1_to_wl(g1), so that rounding drops out. The light passes on the edge's long side. The block
centres (the g2 count centring each block of wavelengths, pinhole_scan.py) are fitted as a
straight line in wavelength, and its value AT the reference wavelength is the scan's g2 centre:
the g2 count that points light of the 'sg' wavelength through the pinhole. If too few blocks
are lit, the centre of all the light is used instead. The slope of that line is the g1:g2
mismatch, in g2 steps per nm.

The offset at a centre is the scan's g2 centre minus the calibration in use at the reference
wavelength, wl_to_g2(g1_to_wl(g1)). The proposed correction is one constant (the offsets'
weighted mean) added to wl_to_g2: the band row on 2026-11-18 showed the pairing already holds
g2's relative pointing to under a step across 720-920 nm (RAM-F5), so what is left is where
it points, not how it changes. The gates say when the offsets disagree enough that one
constant is not enough.

The offsets are only meaningful against the g1 calibration the scan was taken with, so each
scan's g1 counts are compared with what the calibration in use gives for 'sg <centre>'.

The reference scans are those with the pinhole on stage 2's entrance port axis; the scans with
it at stage 1's exit port are a cross-check (the two should agree when the relay between the
stages is aligned), and give the correction only when there are no stage 2 scans.

Frames are loaded through `frame_loader`, so tests can hand in frames without files.
"""

from dataclasses import dataclass, field

import numpy as np

from .frame_names import G2_PINHOLE_SCAN
from .pinhole_scan import PinholeScanSettings, fit_window, scan_light, track_band
from .session import load_frame

REFERENCE_PINHOLE = 'stage2'
CROSS_CHECK_PINHOLE = 'stage1'


@dataclass(frozen=True)
class G2AnalysisSettings:
    scan: PinholeScanSettings = PinholeScanSettings()


@dataclass
class CentreScan:
    """One pinhole position, one centre wavelength: the scan and what it gives."""
    pinhole: str
    centre_nm: int
    records: list                           # session.FrameRecord, in g2 order
    frame_height: int = None
    g1_counts: list = field(default_factory=list)
    master_g1_count: float = None           # wl_to_g1(centre) of the calibration in use
    reference_wavelength_nm: float = None   # g1_to_wl(logged g1 count): the edge, per the
                                            # calibration in use
    band_track: object = None               # pinhole_scan.BandTrack
    light: object = None                    # pinhole_scan.ScanLight
    total_fit: object = None                # pinhole_scan.WindowFit, all lit columns
    block_fits: list = field(default_factory=list)      # WindowFit or None, per block
    centre_count: float = None              # g2 centring the 'sg' wavelength
    centre_uncertainty: float = None
    mismatch_steps_per_nm: float = None     # slope of the block centres against wavelength
    master_count: float = None              # wl_to_g2(reference wavelength), in use
    target_band_row: float = None           # band row (middle column) with the beam centred
    triax_steps: int = None
    slit_width_um: float = None

    @property
    def offset_steps(self):
        if self.centre_count is None or self.master_count is None:
            return None
        return self.centre_count - self.master_count

    @property
    def rows_per_g2_step(self):
        return self.band_track.row_at_middle[0] if self.band_track is not None else None


@dataclass
class ProposedG2Offset:
    """The constant added to wl_to_g2, and the master entries it gives."""
    pinhole: str
    offset_steps: float
    offset_uncertainty: float
    spread_steps: float                     # largest minus smallest offset over the centres
    centres_nm: list
    wl_to_g2: list
    g2_to_wl: list


@dataclass
class G2SessionAnalysis:
    settings: G2AnalysisSettings
    frames_found: object                    # session.FramesFound
    scans: list = field(default_factory=list)       # CentreScan
    proposed: ProposedG2Offset = None
    master: dict = field(default_factory=dict)      # the master's manual_g1 and manual_g2

    def scans_at(self, pinhole):
        return [scan for scan in self.scans if scan.pinhole == pinhole]

    @property
    def reference_pinhole(self):
        """The pinhole position the correction comes from."""
        return REFERENCE_PINHOLE if self.scans_at(REFERENCE_PINHOLE) else CROSS_CHECK_PINHOLE


def group_scans(frames_found):
    """CentreScan per (pinhole, centre), records sorted by g2 count."""
    groups = {}
    for record in frames_found.records:
        frame_name = record.frame_name
        if frame_name.kind != G2_PINHOLE_SCAN or record.frame_path is None or \
                record.g2_count is None:
            continue
        groups.setdefault((frame_name.pinhole, frame_name.centre_nm), []).append(record)
    return [CentreScan(pinhole=pinhole, centre_nm=centre,
                       records=sorted(records, key=lambda record: record.g2_count))
            for (pinhole, centre), records in sorted(groups.items())]


def _centre_at_wavelength(block_wavelengths, block_fits, centre_nm):
    """(centre count at centre_nm, its uncertainty, slope steps/nm) from the block centres'
    straight line, or None when fewer than two blocks have a centre."""
    points = [(wavelength, fit.centre_count, max(fit.centre_uncertainty, 1e-3))
              for wavelength, fit in zip(block_wavelengths, block_fits) if fit is not None]
    if len(points) < 2:
        return None
    wavelengths, centres, uncertainties = (np.array(column) for column in zip(*points))
    coefficients, covariance = np.polyfit(wavelengths - centre_nm, centres, 1,
                                          w=1 / uncertainties, cov='unscaled')
    return float(coefficients[1]), float(np.sqrt(covariance[1, 1])), float(coefficients[0])


def analyse_scan(scan, master, settings, frame_loader):
    """Fill one CentreScan in place."""
    frames = [frame_loader(record.frame_path) for record in scan.records]
    images = [frame.image for frame in frames]
    g2_counts = [record.g2_count for record in scan.records]
    scan.frame_height = images[0].shape[0]
    scan.g1_counts = sorted({record.g1_count for record in scan.records
                             if record.g1_count is not None})
    scan.triax_steps = scan.records[0].triax_steps
    scan.slit_width_um = scan.records[0].slit_width_um
    scan.reference_wavelength_nm = float(scan.centre_nm)
    if 'manual_g1' in master:
        scan.master_g1_count = float(np.polyval(master['manual_g1']['wl_to_g1'], scan.centre_nm))
        if len(scan.g1_counts) == 1:
            scan.reference_wavelength_nm = float(np.polyval(master['manual_g1']['g1_to_wl'],
                                                            scan.g1_counts[0]))
    if 'manual_g2' in master:
        scan.master_count = float(np.polyval(master['manual_g2']['wl_to_g2'],
                                             scan.reference_wavelength_nm))
    scan.band_track = track_band(images, g2_counts, settings.scan)
    if scan.band_track is None:
        return scan
    scan.light = scan_light(images, frames[0].wavelength_nm, g2_counts, scan.band_track,
                            settings.scan)
    scan.total_fit = fit_window(scan.light.g2_counts, scan.light.total_light)
    scan.block_fits = [fit_window(scan.light.g2_counts, light)
                       for light in scan.light.block_light]
    at_wavelength = _centre_at_wavelength(scan.light.block_wavelengths_nm, scan.block_fits,
                                          scan.reference_wavelength_nm)
    if at_wavelength is not None:
        scan.centre_count, scan.centre_uncertainty, scan.mismatch_steps_per_nm = at_wavelength
    elif scan.total_fit is not None:
        scan.centre_count = scan.total_fit.centre_count
        scan.centre_uncertainty = scan.total_fit.centre_uncertainty
    if scan.centre_count is not None:
        scan.target_band_row = scan.band_track.row(scan.centre_count)
    return scan


def _shifted_polynomial(coefficients, shift):
    """Coefficients of p(x - shift), for p given by coefficients (highest power first)."""
    return [float(value) for value in
            np.poly1d(coefficients)(np.poly1d([1.0, -shift])).coeffs]


def propose_g2_offset(session_analysis):
    """ProposedG2Offset from the reference pinhole's scans, or None."""
    master = session_analysis.master
    pinhole = session_analysis.reference_pinhole
    scans = [scan for scan in session_analysis.scans_at(pinhole) if scan.offset_steps is not None]
    if not scans or 'manual_g2' not in master:
        return None
    offsets = np.array([scan.offset_steps for scan in scans])
    weights = 1 / np.array([max(scan.centre_uncertainty or 1.0, 0.05) for scan in scans]) ** 2
    offset = float(np.sum(weights * offsets) / np.sum(weights))
    uncertainty = float(1 / np.sqrt(np.sum(weights)))
    wl_to_g2 = [float(value) for value in master['manual_g2']['wl_to_g2']]
    wl_to_g2[-1] += offset
    return ProposedG2Offset(
        pinhole=pinhole, offset_steps=offset, offset_uncertainty=uncertainty,
        spread_steps=float(np.ptp(offsets)), centres_nm=[scan.centre_nm for scan in scans],
        wl_to_g2=wl_to_g2,
        g2_to_wl=_shifted_polynomial(master['manual_g2']['g2_to_wl'], offset))


def analyse_g2_session(frames_found, master_calibration, settings=G2AnalysisSettings(),
                       frame_loader=load_frame):
    """G2SessionAnalysis of a session read by session.read_session."""
    session_analysis = G2SessionAnalysis(
        settings=settings, frames_found=frames_found,
        master={key: master_calibration[key] for key in ('manual_g1', 'manual_g2')
                if key in master_calibration})
    session_analysis.scans = [analyse_scan(scan, master_calibration, settings, frame_loader)
                              for scan in group_scans(frames_found)]
    session_analysis.proposed = propose_g2_offset(session_analysis)
    return session_analysis

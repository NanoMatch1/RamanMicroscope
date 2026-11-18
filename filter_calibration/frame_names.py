"""
The names of the stage 1 edge frames: written by the run files, read back by the analysis.

A saved frame does not record the grating positions (the run log does, in 'allmotors'), so its
name says what kind of frame it is and where it was taken. Formatting and parsing live together
here, so every name a run file writes is one the analysis can read.

    edge walk        s1edge_t800_g1m020            centre 800 nm, g1 20 steps below 'sg 800'
    single steps     s1step_t800_n007_g1m013       the 7th single step, g1 at -13
    repeatability    s1rep_t800_c2_triax_from720   cycle 2, after the TRIAX alone went to the
                                                   720 nm centre and back (visits: start, still,
                                                   triax_from<nm>, gratings_from<nm>)
    axis reference   s1axis_t800_arhg              Ar-Hg frame at the TRIAX position of centre 800
    g2 pinhole scan  s1g2_stage2_t800_g2m012       pinhole on stage 2's entrance axis (stage2) or
                                                   at stage 1's exit (stage1); g2 12 steps below
                                                   'sg 800', g1 where 'sg 800' put it
    reference        s1ref_<anything>              taken by hand (slit series, dark, check pair)

Names are lower case: typed commands are lower-cased by the application.
"""

import re
from dataclasses import dataclass

EDGE_WALK = 'edge_walk'
SINGLE_STEP = 'single_step'
REPEATABILITY = 'repeatability'
AXIS_REFERENCE = 'axis_reference'
G2_PINHOLE_SCAN = 'g2_pinhole_scan'
REFERENCE = 'reference'

START_VISIT = 'start'
STILL_VISIT = 'still'
TRIAX_VISIT_PREFIX = 'triax_from'
GRATINGS_VISIT_PREFIX = 'gratings_from'

_OFFSET = r'g1([mp])(\d{3})'
_G2_OFFSET = r'g2([mp])(\d{3})'
PINHOLE_POSITIONS = {
    'stage2': "on stage 2's entrance port axis",
    'stage1': "at stage 1's exit port",
}
_PATTERNS = {
    EDGE_WALK: re.compile(rf'^s1edge_t(?P<centre>\d+)_{_OFFSET}$'),
    SINGLE_STEP: re.compile(rf'^s1step_t(?P<centre>\d+)_n(?P<sequence>\d+)_{_OFFSET}$'),
    REPEATABILITY: re.compile(r'^s1rep_t(?P<centre>\d+)_c(?P<sequence>\d+)_(?P<visit>[a-z0-9_]+)$'),
    AXIS_REFERENCE: re.compile(r'^s1axis_t(?P<centre>\d+)_arhg$'),
    G2_PINHOLE_SCAN: re.compile(rf'^s1g2_(?P<pinhole>{"|".join(PINHOLE_POSITIONS)})'
                                rf'_t(?P<centre>\d+)_{_G2_OFFSET}$'),
    REFERENCE: re.compile(r'^s1ref_[a-z0-9_]+$'),
}


@dataclass(frozen=True)
class FrameName:
    """What a frame's name says about it. Fields a kind does not use are None."""
    name: str
    kind: str
    centre_nm: int = None
    g1_offset_steps: int = None     # g1 steps from where 'sg <centre>' put it
    sequence: int = None            # single-step number, or repeatability cycle
    visit: str = None               # repeatability: start, still, triax_from<nm>, gratings_from<nm>
    g2_offset_steps: int = None     # g2 pinhole scan: g2 steps from where 'sg <centre>' put it
    pinhole: str = None             # g2 pinhole scan: where the pinhole was (PINHOLE_POSITIONS)

    @property
    def is_edge_free(self):
        """An edge-walk frame with g1 moved well off the edge (open or closed)."""
        return self.kind == EDGE_WALK and abs(self.g1_offset_steps) >= EDGE_FREE_THRESHOLD_STEPS

    @property
    def visit_kind(self):
        """Repeatability: what moved before the frame ('start', 'still', 'triax', 'gratings')."""
        if self.visit is None:
            return None
        for prefix, label in ((TRIAX_VISIT_PREFIX, 'triax'), (GRATINGS_VISIT_PREFIX, 'gratings')):
            if self.visit.startswith(prefix):
                return label
        return self.visit


EDGE_FREE_THRESHOLD_STEPS = 100


def offset_label(offset_steps):
    """'p010' for +10 steps, 'm020' for -20: file names stay lower case and sign-safe."""
    return f"{'m' if offset_steps < 0 else 'p'}{abs(offset_steps):03d}"


def edge_walk_name(centre_nm, g1_offset_steps):
    return f's1edge_t{centre_nm}_g1{offset_label(g1_offset_steps)}'


def single_step_name(centre_nm, sequence, g1_offset_steps):
    return f's1step_t{centre_nm}_n{sequence:03d}_g1{offset_label(g1_offset_steps)}'


def repeatability_name(centre_nm, cycle, visit):
    return f's1rep_t{centre_nm}_c{cycle}_{visit}'


def triax_visit(away_centre_nm):
    return f'{TRIAX_VISIT_PREFIX}{away_centre_nm}'


def gratings_visit(away_centre_nm):
    return f'{GRATINGS_VISIT_PREFIX}{away_centre_nm}'


def axis_reference_name(centre_nm):
    return f's1axis_t{centre_nm}_arhg'


def g2_pinhole_scan_name(pinhole, centre_nm, g2_offset_steps):
    if pinhole not in PINHOLE_POSITIONS:
        raise ValueError(f'pinhole must be one of {list(PINHOLE_POSITIONS)}, not {pinhole!r}')
    return f's1g2_{pinhole}_t{centre_nm}_g2{offset_label(g2_offset_steps)}'


def parse_frame_name(name):
    """The FrameName for a frame name, or None if it is not a stage 1 edge frame."""
    for kind, pattern in _PATTERNS.items():
        match = pattern.match(name)
        if match is None:
            continue
        fields = match.groupdict()
        offset = None
        if kind in (EDGE_WALK, SINGLE_STEP, G2_PINHOLE_SCAN):
            sign_letter, digits = match.groups()[-2:]
            offset = (-1 if sign_letter == 'm' else 1) * int(digits)
        return FrameName(
            name=name, kind=kind,
            centre_nm=int(fields['centre']) if 'centre' in fields else None,
            g1_offset_steps=offset if kind in (EDGE_WALK, SINGLE_STEP) else None,
            sequence=int(fields['sequence']) if fields.get('sequence') else None,
            visit=fields.get('visit'),
            g2_offset_steps=offset if kind == G2_PINHOLE_SCAN else None,
            pinhole=fields.get('pinhole'))
    return None

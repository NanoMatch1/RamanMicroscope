"""
A stage 1 edge session read back from disk: which frame was taken where.

A saved frame records neither the grating counts nor the TRIAX steps, so they come from the run
logs that `runfile` writes (data/runfile_logs/): each line is 'time<TAB>command<TAB>result', and
the analysis reads
- 'allmotors' (a dict of motor counts) before each frame,
- 'rg' (the TRIAX's steps) and 'ren' (the entrance slit width in um), the latest before it,
- 'filename <name>' then 'acquire': one frame of that name.
The frame's kind and nominal position come from its name (frame_names.py).

Frames are found under the data directory by name, wherever they sit: on the lab PC each name
has its own folder (data/<name>/<name>_000000.npz); a copied session may group them further.
Each acquire of a name takes the next index, so the k-th acquire of a name in these logs (in
time order) is <name>_00000k. If a folder holds more indices than these logs acquired, older
frames of the same name are present: the newest indices are taken and FramesFound says so.
"""

import ast
import glob
import json
import os
from dataclasses import dataclass, field

import numpy as np

from .frame_names import parse_frame_name


@dataclass(frozen=True)
class FrameRecord:
    """One acquired frame: its name's meaning, the instrument state the log gives, its file."""
    frame_name: object              # FrameName
    index: int                      # n-th acquire of this name in the logs (the file's index)
    motor_counts: dict              # 'allmotors' before the frame ({} if none)
    triax_steps: int                # latest 'rg' before the frame (None if none)
    slit_width_um: float            # latest 'ren' before the frame (None if none)
    acquired_at: str                # time of the 'acquire' line
    run_log_path: str
    frame_path: str = None          # None if the file was not found

    @property
    def name(self):
        return self.frame_name.name

    @property
    def g1_count(self):
        return self.motor_counts.get('g1')

    @property
    def g2_count(self):
        return self.motor_counts.get('g2')


@dataclass
class FramesFound:
    """What reading the logs found: the frames, and anything that did not line up."""
    records: list = field(default_factory=list)
    missing_frames: list = field(default_factory=list)      # acquired, but no file
    older_frames_present: list = field(default_factory=list)  # names with extra indices on disk
    unrecognised_names: list = field(default_factory=list)  # acquired, but not a stage 1 name
    run_log_paths: list = field(default_factory=list)


def read_run_log(path):
    """[(time, command, result text)] for every command line of a run log."""
    entries = []
    with open(path) as run_log:
        for line in run_log:
            if line.startswith('#') or not line.strip():
                continue
            fields = line.rstrip('\n').split('\t')
            if len(fields) >= 2:
                entries.append((fields[0], fields[1], fields[2] if len(fields) > 2 else ''))
    return entries


def _parse_number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_motor_counts(text):
    try:
        counts = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return {}
    return counts if isinstance(counts, dict) else {}


def _frame_files_by_name(data_directory):
    """{frame name: sorted list of its .npz paths} for every frame under the data directory."""
    files = {}
    for path in glob.glob(os.path.join(data_directory, '**', '*.npz'), recursive=True):
        stem = os.path.basename(path)[:-4]
        name, separator, index_text = stem.rpartition('_')
        if separator and index_text.isdigit():
            files.setdefault(name, []).append(path)
    return {name: sorted(paths) for name, paths in files.items()}


def read_session(run_log_paths, data_directory):
    """FramesFound for these run logs (any order: they are read in time order)."""
    found = FramesFound(run_log_paths=list(run_log_paths))
    acquisitions = []
    for path in run_log_paths:
        motor_counts, triax_steps, slit_width_um, pending_name = {}, None, None, None
        for time, command, result in read_run_log(path):
            if command == 'allmotors':
                motor_counts = _parse_motor_counts(result)
            elif command == 'rg':
                steps = _parse_number(result)
                triax_steps = int(steps) if steps is not None else triax_steps
            elif command == 'ren':
                slit_width_um = _parse_number(result)
            elif command.startswith('filename '):
                pending_name = command.split(maxsplit=1)[1].strip()
            elif command == 'acquire' and pending_name is not None:
                acquisitions.append((time, pending_name, dict(motor_counts), triax_steps,
                                     slit_width_um, path))
    acquisitions.sort(key=lambda acquisition: acquisition[0])

    files = _frame_files_by_name(data_directory)
    acquires_per_name = {}
    for acquisition in acquisitions:
        acquires_per_name[acquisition[1]] = acquires_per_name.get(acquisition[1], 0) + 1
    for name, count in acquires_per_name.items():
        if len(files.get(name, [])) > count:
            found.older_frames_present.append(name)

    seen_per_name = {}
    for time, name, motor_counts, triax_steps, slit_width_um, path in acquisitions:
        frame_name = parse_frame_name(name)
        if frame_name is None:
            found.unrecognised_names.append(name)
            continue
        occurrence = seen_per_name.get(name, 0)
        seen_per_name[name] = occurrence + 1
        name_files = files.get(name, [])
        first_index = max(len(name_files) - acquires_per_name[name], 0)
        file_position = first_index + occurrence
        frame_path = name_files[file_position] if file_position < len(name_files) else None
        if frame_path is None:
            found.missing_frames.append(name)
        found.records.append(FrameRecord(
            frame_name=frame_name, index=file_position, motor_counts=motor_counts,
            triax_steps=triax_steps, slit_width_um=slit_width_um, acquired_at=time,
            run_log_path=path, frame_path=frame_path))
    return found


@dataclass
class Frame:
    """A loaded frame."""
    image: np.ndarray               # (rows, columns), counts
    wavelength_nm: np.ndarray       # per column, the axis saved with the frame
    metadata: dict


def load_frame(path):
    with np.load(path, allow_pickle=False) as stored:
        metadata = json.loads(str(stored['metadata'])) if 'metadata' in stored.files else {}
        return Frame(image=stored['image'].astype(float),
                     wavelength_nm=np.asarray(stored['wavelength'], dtype=float),
                     metadata=metadata)

"""
Which software took a measurement: recorded in every line walk, so a result traces to its code.

Reads git without requiring it: on a machine without git, or outside a clone,
the fields say 'unknown' instead of failing the walk.
"""

import subprocess


def _git(repository_directory, *arguments):
    try:
        completed = subprocess.run(['git', '-C', str(repository_directory), *arguments],
                                   capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def software_version(repository_directory):
    """{'commit', 'branch', 'uncommitted_changes'} of the clone the application runs from."""
    status = _git(repository_directory, 'status', '--porcelain', '--untracked-files=no')
    return {
        'commit': _git(repository_directory, 'rev-parse', '--short=10', 'HEAD') or 'unknown',
        'branch': _git(repository_directory, 'rev-parse', '--abbrev-ref', 'HEAD') or 'unknown',
        'uncommitted_changes': None if status is None else bool(status),
    }

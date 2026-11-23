"""
Which software took or fitted a result, from what: recorded in every line walk and every
calibration report, so a result traces to its code and its inputs.

- software_version: the commit, branch and whether the clone had uncommitted changes.
- file_sha256: an input file's hash. A report lists its inputs with their hashes, so it can
  say whether a file is still the one it used, and find that file again after it is renamed
  or copied elsewhere.
- command_line_text: the command that made a report, to re-run it.

Reads git without requiring it: on a machine without git, or outside a clone,
the fields say 'unknown' instead of failing.
"""

import hashlib
import os
import subprocess
import sys


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


def software_version_text(version):
    """One line: 'commit (branch, uncommitted changes: ...)'."""
    return (f"{version['commit']} ({version['branch']}, "
            f"uncommitted changes: {version['uncommitted_changes']})")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def command_line_text(module_name):
    """The command that is running, as 'python -m <module_name> <arguments>'."""
    return ' '.join([os.path.basename(sys.executable), '-m', module_name] + sys.argv[1:])

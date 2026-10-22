"""Stop personal details and data files from reaching this public repository.

This repository is public, and anything pushed to any branch is public the
moment it is pushed. These checks catch the common accidents before that:
personal email addresses, personal file paths, private share links, acquired
data and large binaries, and a git identity that would publish a personal
email address in the commit itself.

Two entry points, one set of checks:

    python tools/repo_guard.py staged
        What the pre-commit hook runs: checks the staged changes and the
        identity that is about to author the commit.

    python tools/repo_guard.py range <base> <head>
        What CI runs: checks every change and every commit identity
        between two commits.

Only ADDED lines and ADDED/MODIFIED files are checked, so historical content
already in the repository never blocks new work. A line that genuinely needs
to contain a flagged pattern can carry the marker `repo-guard: allow`.

Install the hook once per clone:  git config core.hooksPath .githooks

Uses only the standard library so that it runs on any Python 3 the lab PC
happens to have, with nothing to install.
"""
import argparse
import dataclasses
import re
import subprocess
import sys

ALLOW_MARKER = "repo-guard: allow"

# The guard's own source and tests necessarily contain the patterns they
# look for, so they are the one fixed exemption.
GUARD_SELF_PATHS = ("tools/repo_guard.py", "test_repo_guard.py")

MAX_FILE_BYTES = 1_000_000

DATA_FILE_EXTENSIONS = (
    ".npy", ".npz", ".spe", ".sif", ".h5", ".hdf5", ".tif", ".tiff",
    ".mat", ".pkl", ".pickle", ".zip", ".7z",
)

ALLOWED_EMAIL_DOMAINS = ("users.noreply.github.com", "example.com", "example.org")
ALLOWED_EMAIL_ADDRESSES = ("noreply@github.com", "git@github.com", "noreply@anthropic.com")

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

NOREPLY_HELP = (
    "use your GitHub no-reply address (GitHub -> Settings -> Emails), e.g.\n"
    "    git config user.email \"<id>+<username>@users.noreply.github.com\""
)


@dataclasses.dataclass(frozen=True)
class Violation:
    """One problem found, with enough context to fix it."""

    check_name: str
    location: str
    detail: str
    hint: str

    def __str__(self):
        return f"[{self.check_name}] {self.location}: {self.detail}\n    -> {self.hint}"


@dataclasses.dataclass(frozen=True)
class AddedLine:
    """A line added by the change under review."""

    path: str
    line_number: int
    text: str


@dataclasses.dataclass(frozen=True)
class ChangedFile:
    """A file added or modified by the change under review."""

    path: str
    status: str  # "A" added, "M" modified, "R" renamed, "C" copied
    size_bytes: int


# ── Check registries ──────────────────────────────────────────────────────────
# Each check registers itself here at definition time. The registries are the
# single source of truth for what runs and for the help text (--list).

LINE_CHECKS = {}
FILE_CHECKS = {}


def line_check(name, hint):
    """Register a function(text) -> detail-or-None, run on every added line."""

    def register(function):
        LINE_CHECKS[name] = (function, hint)
        return function

    return register


def file_check(name, hint):
    """Register a function(ChangedFile) -> detail-or-None, run on every changed file."""

    def register(function):
        FILE_CHECKS[name] = (function, hint)
        return function

    return register


def is_allowed_email(address):
    """True for addresses that are safe to publish (no-reply, placeholders)."""
    address = address.lower()
    domain = address.rsplit("@", 1)[1]
    return address in ALLOWED_EMAIL_ADDRESSES or domain.endswith(ALLOWED_EMAIL_DOMAINS)


@line_check("personal-email", "remove it, or use a GitHub no-reply / example.com address")
def find_personal_email(text):
    """Flag an email address that is not a no-reply or placeholder address."""
    for address in EMAIL_PATTERN.findall(text):
        if not is_allowed_email(address):
            return f"email address {address}"
    return None


PERSONAL_PATH_PATTERN = re.compile(
    # A real user name follows; a documentation placeholder like <name> does not.
    r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s'\"<]+"  # C:\Users\name
    r"|/home/[A-Za-z0-9_.-]+/"                    # /home/name/
    r"|/Users/[A-Za-z0-9_.-]+/"                   # /Users/name/ (macOS)
)


@line_check("personal-path", "build the path relative to the repository (os.path.dirname(__file__))")
def find_personal_path(text):
    """Flag an absolute path inside someone's home directory."""
    match = PERSONAL_PATH_PATTERN.search(text)
    return f"home-directory path {match.group(0)!r}" if match else None


SHARE_LINK_PATTERN = re.compile(
    r"sharepoint\.com|onedrive\.live\.com|1drv\.ms|drive\.google\.com|dropbox\.com/s",
    re.IGNORECASE,
)


@line_check("share-link", "private share links belong in the lab notebook, not a public repository")
def find_share_link(text):
    """Flag a link into a personal cloud drive."""
    match = SHARE_LINK_PATTERN.search(text)
    return f"cloud share link ({match.group(0)})" if match else None


@file_check("data-file", "acquired data lives under data/ (git-ignored), never in the repository")
def find_data_file(changed_file):
    """Flag a newly added file whose extension marks it as acquired data."""
    if changed_file.status == "A" and changed_file.path.lower().endswith(DATA_FILE_EXTENSIONS):
        return "data file added"
    return None


@file_check("large-file", f"keep files under {MAX_FILE_BYTES // 1000} kB; git history never forgets a binary")
def find_large_file(changed_file):
    """Flag a file over the size limit."""
    if changed_file.size_bytes > MAX_FILE_BYTES:
        return f"{changed_file.size_bytes / 1e6:.1f} MB"
    return None


# ── Running the checks ───────────────────────────────────────────────────────

def is_exempt_path(path):
    """True for the guard's own files, which necessarily contain the patterns."""
    return path in GUARD_SELF_PATHS


def check_lines(added_lines):
    """Run every registered line check over the added lines."""
    violations = []
    for added_line in added_lines:
        if is_exempt_path(added_line.path) or ALLOW_MARKER in added_line.text:
            continue
        for name, (function, hint) in LINE_CHECKS.items():
            detail = function(added_line.text)
            if detail:
                location = f"{added_line.path}:{added_line.line_number}"
                violations.append(Violation(name, location, detail, hint))
    return violations


def check_files(changed_files):
    """Run every registered file check over the changed files."""
    violations = []
    for changed_file in changed_files:
        if is_exempt_path(changed_file.path):
            continue
        for name, (function, hint) in FILE_CHECKS.items():
            detail = function(changed_file)
            if detail:
                violations.append(Violation(name, changed_file.path, detail, hint))
    return violations


def check_identity(email, location):
    """Flag a commit identity that would publish a personal email address."""
    if "@" in email and is_allowed_email(email):
        return []
    return [Violation("identity", location, f"commit email {email!r} would be published", NOREPLY_HELP)]


# ── Reading changes from git ─────────────────────────────────────────────────

def run_git(*arguments):
    """Run a git command in the current repository and return its stdout."""
    return subprocess.run(
        ["git", *arguments], capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
    ).stdout


HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_added_lines(unified_diff):
    """Extract (path, line number, text) for every added line of a zero-context diff."""
    added_lines = []
    current_path, next_line_number = None, 0
    for line in unified_diff.splitlines():
        if line.startswith("+++ "):
            current_path = None if line == "+++ /dev/null" else line[6:]  # strip "+++ b/"
        elif line.startswith("@@"):
            next_line_number = int(HUNK_HEADER.match(line).group(1))
        elif line.startswith("+") and current_path is not None:
            added_lines.append(AddedLine(current_path, next_line_number, line[1:]))
            next_line_number += 1
    return added_lines


def parse_changed_files(name_status_output, size_of):
    """Turn `git diff --name-status` output into ChangedFile records."""
    changed_files = []
    for line in name_status_output.splitlines():
        fields = line.split("\t")
        status, path = fields[0][0], fields[-1]
        changed_files.append(ChangedFile(path, status, size_of(path)))
    return changed_files


def collect_staged():
    """Added lines and changed files in the index (what is about to be committed)."""
    diff_arguments = ["diff", "--cached", "--no-color", "--no-ext-diff", "--diff-filter=ACMR"]
    added_lines = parse_added_lines(run_git(*diff_arguments, "--unified=0"))
    changed_files = parse_changed_files(
        run_git(*diff_arguments, "--name-status"),
        lambda path: int(run_git("cat-file", "-s", f":{path}")),
    )
    return added_lines, changed_files


def collect_range(base, head):
    """Added lines and changed files between two commits."""
    diff_arguments = ["diff", "--no-color", "--no-ext-diff", "--diff-filter=ACMR", base, head]
    added_lines = parse_added_lines(run_git(*diff_arguments, "--unified=0"))
    changed_files = parse_changed_files(
        run_git(*diff_arguments, "--name-status"),
        lambda path: int(run_git("cat-file", "-s", f"{head}:{path}")),
    )
    return added_lines, changed_files


def commit_identities(base, head):
    """(commit, role, email) for every author and committer in base..head."""
    identities = []
    for line in run_git("log", "--format=%h %ae %ce", f"{base}..{head}").splitlines():
        commit, author_email, committer_email = line.split(" ")
        identities.append((commit, "author", author_email))
        identities.append((commit, "committer", committer_email))
    return identities


# ── Command line ─────────────────────────────────────────────────────────────

def run_staged():
    """Pre-commit mode: staged changes plus the identity about to commit."""
    added_lines, changed_files = collect_staged()
    configured_email = run_git("config", "user.email").strip()
    return (check_identity(configured_email, "git config user.email")
            + check_lines(added_lines) + check_files(changed_files))


def run_range(base, head):
    """CI mode: every change and every commit identity in base..head."""
    added_lines, changed_files = collect_range(base, head)
    violations = []
    for commit, role, email in commit_identities(base, head):
        violations += check_identity(email, f"commit {commit} {role}")
    return violations + check_lines(added_lines) + check_files(changed_files)


def describe_checks():
    """Help text generated from the registries, so it can never drift."""
    lines = ["identity: commit email must be a no-reply or placeholder address"]
    for name, (function, hint) in {**LINE_CHECKS, **FILE_CHECKS}.items():
        lines.append(f"{name}: {function.__doc__.strip()}")
    return "\n".join(lines)


def main(argv=None):
    """Parse arguments, run the requested mode, print violations, return exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("staged", help="check staged changes (pre-commit hook)")
    range_parser = subparsers.add_parser("range", help="check base..head (CI)")
    range_parser.add_argument("base")
    range_parser.add_argument("head")
    subparsers.add_parser("list", help="list the checks")
    arguments = parser.parse_args(argv)

    if arguments.mode == "list":
        print(describe_checks())
        return 0
    violations = run_staged() if arguments.mode == "staged" else run_range(arguments.base, arguments.head)
    if not violations:
        return 0
    print(f"repo-guard: {len(violations)} problem(s) — this repository is public.\n", file=sys.stderr)
    for violation in violations:
        print(violation, file=sys.stderr)
    print(f"\nA line that genuinely needs a flagged pattern can carry '{ALLOW_MARKER}'.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

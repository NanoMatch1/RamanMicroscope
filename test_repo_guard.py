"""
Tests for tools/repo_guard.py, the public-repository safety checks.

Two layers, matching the rest of the repository:
- unit tests of each registered check and of the diff parsing, with no git;
- workflow tests that build a throwaway git repository with the real
  pre-commit hook installed and make real commits through it, plus the CI
  range mode over those commits.

Run with:  python -m pytest test_repo_guard.py -q
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPOSITORY_ROOT / "tools"))

import repo_guard  # noqa: E402  (path set up above; tools/ is not a package)

NOREPLY_EMAIL = "12345+someone@users.noreply.github.com"


# ── Unit: line checks ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "contact jane.doe@gmail.com for access",
    "author = 'someone@unimelb.edu.au'",
])
def test_personal_email_is_flagged(text):
    assert repo_guard.find_personal_email(text)


@pytest.mark.parametrize("text", [
    f"git config user.email {NOREPLY_EMAIL}",
    'git config --global user.email "you@example.com"',
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "git clone git@github.com:NanoMatch1/RamanMicroscope.git",
    "@ui_callable",
])
def test_safe_addresses_pass(text):
    assert repo_guard.find_personal_email(text) is None


@pytest.mark.parametrize("text", [
    r"dataDir = r'C:\Users\Sam\Data\scan_01'",
    "path = 'C:/Users/someone/Desktop/x.csv'",
    "open('/home/match/notes.txt')",
    "open('/Users/sam/Documents/run.json')",
])
def test_personal_path_is_flagged(text):
    assert repo_guard.find_personal_path(text)


def test_relative_path_passes():
    assert repo_guard.find_personal_path("os.path.join(os.path.dirname(__file__), 'data')") is None


def test_documentation_placeholder_path_passes():
    assert repo_guard.find_personal_path(r"never commit C:\Users\<name>\...") is None


def test_share_link_is_flagged():
    assert repo_guard.find_share_link("https://uni-my.sharepoint.com/:f:/g/personal/x")
    assert repo_guard.find_share_link("see https://1drv.ms/f/s!abc")
    assert repo_guard.find_share_link("https://github.com/NanoMatch1/RamanMicroscope") is None


# ── Unit: file checks ────────────────────────────────────────────────────────

def test_added_data_file_is_flagged_but_modified_one_is_not():
    added = repo_guard.ChangedFile("scan/spectrum.npz", "A", 100)
    modified = repo_guard.ChangedFile("scan/spectrum.npz", "M", 100)
    assert repo_guard.find_data_file(added)
    assert repo_guard.find_data_file(modified) is None


def test_large_file_is_flagged():
    assert repo_guard.find_large_file(repo_guard.ChangedFile("big.pdf", "A", 5_000_000))
    assert repo_guard.find_large_file(repo_guard.ChangedFile("small.md", "A", 2_000)) is None


# ── Unit: running checks, exemptions, identity ───────────────────────────────

def test_allow_marker_skips_a_line():
    lines = [repo_guard.AddedLine("a.md", 1, "vendor support: help@vendor.com  # repo-guard: allow")]
    assert repo_guard.check_lines(lines) == []


def test_guard_self_paths_are_exempt():
    lines = [repo_guard.AddedLine("test_repo_guard.py", 1, "x@gmail.com")]
    assert repo_guard.check_lines(lines) == []


def test_violation_reports_check_name_and_location():
    lines = [repo_guard.AddedLine("docs/notes.md", 7, "mail me: x@gmail.com")]
    (violation,) = repo_guard.check_lines(lines)
    assert violation.check_name == "personal-email"
    assert violation.location == "docs/notes.md:7"


@pytest.mark.parametrize("email, ok", [
    (NOREPLY_EMAIL, True),
    ("noreply@github.com", True),       # GitHub as committer of web edits
    ("someone@gmail.com", False),
    ("match@Raman", False),             # lab PC default: not a real address
    ("", False),
])
def test_identity_check(email, ok):
    assert (repo_guard.check_identity(email, "here") == []) is ok


def test_every_registered_check_appears_in_help():
    help_text = repo_guard.describe_checks()
    for name in {**repo_guard.LINE_CHECKS, **repo_guard.FILE_CHECKS}:
        assert name in help_text


# ── Unit: diff parsing ───────────────────────────────────────────────────────

def test_parse_added_lines_tracks_paths_and_line_numbers():
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -3,0 +4,2 @@\n"
        "+first\n"
        "+second\n"
        "diff --git a/old.md b/old.md\n"
        "--- a/old.md\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-gone\n"
    )
    parsed = repo_guard.parse_added_lines(diff)
    assert parsed == [
        repo_guard.AddedLine("x.py", 4, "first"),
        repo_guard.AddedLine("x.py", 5, "second"),
    ]


def test_parse_changed_files_uses_new_path_for_renames():
    output = "A\tnew.npz\nR100\told.md\tdocs/new.md\n"
    parsed = repo_guard.parse_changed_files(output, lambda path: 42)
    assert parsed == [
        repo_guard.ChangedFile("new.npz", "A", 42),
        repo_guard.ChangedFile("docs/new.md", "R", 42),
    ]


# ── Workflow: the real hook in a throwaway repository ────────────────────────

def git(repository, *arguments, check=True):
    """Run git in the throwaway repository."""
    return subprocess.run(["git", "-C", str(repository), *arguments],
                          capture_output=True, text=True, check=check)


@pytest.fixture
def guarded_repository(tmp_path):
    """A fresh repository laid out like this one, with the hook enabled."""
    shutil.copytree(REPOSITORY_ROOT / ".githooks", tmp_path / ".githooks")
    (tmp_path / "tools").mkdir()
    shutil.copy(REPOSITORY_ROOT / "tools" / "repo_guard.py", tmp_path / "tools")
    git(tmp_path, "init", "-q", "-b", "develop")
    git(tmp_path, "config", "user.name", "Test User")
    git(tmp_path, "config", "user.email", NOREPLY_EMAIL)
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "chore: guard")
    git(tmp_path, "config", "core.hooksPath", ".githooks")
    return tmp_path


def commit_file(repository, name, content):
    """Stage one file and try to commit it; return the completed process."""
    path = repository / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)
    git(repository, "add", name)
    return git(repository, "commit", "-q", "-m", f"add {name}", check=False)


def test_hook_allows_a_clean_commit(guarded_repository):
    result = commit_file(guarded_repository, "docs/sop.md", "1. Home gratings 1-4.\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name, content, check_name", [
    ("docs/notes.md", "data: https://x-my.sharepoint.com/personal/y\n", "share-link"),
    ("analysis.py", "folder = r'C:\\Users\\Riley\\Data'\n", "personal-path"),
    ("README.md", "questions to someone@gmail.com\n", "personal-email"),
    ("scan_001.npz", b"\x93NUMPY", "data-file"),
])
def test_hook_blocks_a_sensitive_commit(guarded_repository, name, content, check_name):
    result = commit_file(guarded_repository, name, content)
    assert result.returncode != 0
    assert f"[{check_name}]" in result.stderr
    assert git(guarded_repository, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_hook_blocks_a_personal_identity(guarded_repository):
    git(guarded_repository, "config", "user.email", "match@Raman")
    result = commit_file(guarded_repository, "docs/sop.md", "fine content\n")
    assert result.returncode != 0
    assert "[identity]" in result.stderr


def test_range_mode_catches_what_skipped_the_hook(guarded_repository, monkeypatch):
    base = git(guarded_repository, "rev-parse", "HEAD").stdout.strip()
    git(guarded_repository, "config", "user.email", "someone@gmail.com")
    (guarded_repository / "notes.md").write_text("path C:\\Users\\Sam\\x\n")
    git(guarded_repository, "add", "notes.md")
    git(guarded_repository, "commit", "-q", "--no-verify", "-m", "sneak past the hook")
    monkeypatch.chdir(guarded_repository)
    violations = repo_guard.run_range(base, "HEAD")
    assert {v.check_name for v in violations} == {"identity", "personal-path"}


def test_range_mode_passes_clean_history(guarded_repository, monkeypatch):
    base = git(guarded_repository, "rev-parse", "HEAD").stdout.strip()
    commit_file(guarded_repository, "docs/sop.md", "clean\n")
    monkeypatch.chdir(guarded_repository)
    assert repo_guard.run_range(base, "HEAD") == []

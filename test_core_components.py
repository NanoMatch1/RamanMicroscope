"""
Unit tests for the hardware-free core components introduced while making
the application headless: the structures every client shares.

These are the "form 1" discrete unit tests. They import no hardware class,
build no Interface, and need no simulator; each component is exercised in
isolation with explicit inputs and outputs. The "form 2" workflow coverage
of the same components lives in test_headless_simulation.py.

Run with:  python -m pytest test_core_components.py -q
"""

import os
import sys

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from command_result import CommandResult


# ----------------------------------------------------------------------------
# CommandResult
# ----------------------------------------------------------------------------

def test_success_result_reports_ok_and_value():
    result = CommandResult.success('rg', 380000)
    assert result.ok is True
    assert result.value == 380000
    assert result.error is None
    assert result.traceback is None
    assert result.text == '380000'


def test_success_with_no_value_renders_as_empty_text():
    """Consoles use empty text to decide whether to print an acknowledgement."""
    result = CommandResult.success('wai')
    assert result.ok is True
    assert result.text == ''
    assert str(result) == ''


def test_failure_result_captures_exception_and_traceback():
    def raise_inside():
        try:
            int('notanumber')
        except ValueError as exc:
            return CommandResult.failure('acqtime notanumber', exc)

    result = raise_inside()
    assert result.ok is False
    assert result.value is None
    assert result.error.startswith('ValueError:')
    assert 'notanumber' in result.error
    assert 'Traceback' in result.traceback
    assert result.text.startswith('Error: ValueError')
    assert result.command == 'acqtime notanumber'


def test_failure_text_without_traceback_is_still_readable():
    result = CommandResult(command='x', ok=False, error='busy: scan running')
    assert result.text == 'Error: busy: scan running'

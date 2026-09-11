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


# ----------------------------------------------------------------------------
# OperatorPrompt
# ----------------------------------------------------------------------------

import logging

import pytest

from operator_prompt import ConsolePrompt, NonInteractivePrompt, NonInteractiveError


def scripted_input(answers):
    """An input() stand-in that returns the given answers in order."""
    queue = list(answers)

    def fake_input(prompt_text):
        return queue.pop(0)

    return fake_input


def test_console_confirm_accepts_yes_and_no_forms():
    assert ConsolePrompt(scripted_input(['y'])).confirm('Go?') is True
    assert ConsolePrompt(scripted_input(['YES'])).confirm('Go?') is True
    assert ConsolePrompt(scripted_input(['n'])).confirm('Go?') is False
    assert ConsolePrompt(scripted_input(['No'])).confirm('Go?') is False


def test_console_confirm_empty_answer_takes_the_default():
    assert ConsolePrompt(scripted_input([''])).confirm('Go?', default=True) is True
    assert ConsolePrompt(scripted_input([''])).confirm('Go?', default=False) is False


def test_console_confirm_reasks_until_it_gets_a_yes_or_no():
    prompt = ConsolePrompt(scripted_input(['maybe', 'dunno', 'y']))
    assert prompt.confirm('Go?') is True


def test_console_ask_with_choices_reasks_until_valid():
    prompt = ConsolePrompt(scripted_input(['sideways', 'IMAGEMODE']))
    assert prompt.ask('Mode', choices=['imagemode', 'ramanmode']) == 'imagemode'


def test_console_ask_without_choices_returns_stripped_text():
    assert ConsolePrompt(scripted_input(['  12.5 '])).ask('Step') == '12.5'


def test_noninteractive_confirm_returns_default_and_logs(caplog):
    prompt = NonInteractivePrompt(logging.getLogger('test.prompt'))
    with caplog.at_level(logging.WARNING, logger='test.prompt'):
        assert prompt.confirm('Move anyway?') is False
        assert prompt.confirm('Keep going?', default=True) is True
    assert 'Move anyway?' in caplog.text
    assert "answering 'no'" in caplog.text
    assert "answering 'yes'" in caplog.text


def test_noninteractive_ask_raises_a_clear_error():
    prompt = NonInteractivePrompt(logging.getLogger('test.prompt'))
    with pytest.raises(NonInteractiveError) as excinfo:
        prompt.ask('Enter current mode', choices=['imagemode', 'ramanmode'])
    assert 'Enter current mode' in str(excinfo.value)

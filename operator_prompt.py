"""
How library code asks the operator a question, without owning the terminal.

Instrument methods sometimes need a human decision: "already in Raman mode,
move anyway?", "run this calibration over 40 wavelengths?", "detection is
within 50 wavenumbers of the laser line, overwrite the safety?". Calling
``input()`` inside those methods ties them to a terminal: a GUI command
hangs on stdin, a headless run blocks forever, and a remote client can
never answer.

Instead, every class that needs a decision receives an ``OperatorPrompt``
and calls ``confirm`` or ``ask`` on it. The CLI supplies ``ConsolePrompt``
(real ``input()``); everything else gets ``NonInteractivePrompt``, which
declines confirmations with the safe default and refuses open questions
with a clear error. Library code never touches stdin.
"""

import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional, Sequence


class NonInteractiveError(RuntimeError):
    """Raised when a command needs an operator's answer and none is available."""


class OperatorPrompt(ABC):
    """Interface for asking the operator a question."""

    @abstractmethod
    def confirm(self, question: str, default: bool = False) -> bool:
        """
        Ask a yes/no question. ``default`` is the answer when the operator
        gives none, and the answer a non-interactive prompt returns.
        """

    @abstractmethod
    def ask(self, question: str, choices: Optional[Sequence[str]] = None) -> str:
        """
        Ask an open question and return the operator's text. With
        ``choices``, keep asking until the answer is one of them.
        """


class ConsolePrompt(OperatorPrompt):
    """Prompts on the terminal. Only the CLI should construct this."""

    def __init__(self, input_function: Callable[[str], str] = input):
        self._input = input_function

    def confirm(self, question: str, default: bool = False) -> bool:
        hint = '[Y/n]' if default else '[y/N]'
        while True:
            answer = self._input(f"{question} {hint} ").strip().lower()
            if answer == '':
                return default
            if answer in ('y', 'yes'):
                return True
            if answer in ('n', 'no'):
                return False

    def ask(self, question: str, choices: Optional[Sequence[str]] = None) -> str:
        if choices is None:
            return self._input(f"{question}: ").strip()
        options = '/'.join(choices)
        while True:
            answer = self._input(f"{question} ({options}): ").strip().lower()
            if answer in choices:
                return answer


class NonInteractivePrompt(OperatorPrompt):
    """
    The prompt for every context without a terminal: tests, the GUI's
    command path, remote clients. Confirmations resolve to their safe
    default and are logged so the decision is visible; open questions
    cannot be answered and raise.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger('interface.OperatorPrompt')

    def confirm(self, question: str, default: bool = False) -> bool:
        answer = 'yes' if default else 'no'
        self._logger.warning(
            f"Confirmation required but no operator is available; answering "
            f"'{answer}' to: {question}"
        )
        return default

    def ask(self, question: str, choices: Optional[Sequence[str]] = None) -> str:
        raise NonInteractiveError(
            f"This command needs an operator at the terminal to answer: {question}"
        )

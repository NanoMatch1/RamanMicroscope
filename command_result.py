"""
Structured result of one command dispatched through ``Interface``.

Every command line typed at the CLI, entered in a GUI console, or sent by a
remote client passes through ``Interface._command_handler`` and comes back
as one of these. Callers check ``ok`` rather than string-matching the return
value for the word "Error", which is what they had to do when the handler
returned formatted strings on failure.

The class is deliberately plain: no logging, no hardware, no Qt. It is the
shape that crosses every boundary in the application, so it must be
constructible and readable anywhere, including on the wire as JSON.
"""

import traceback
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CommandResult:
    """Outcome of one command: what was asked, whether it worked, and what came back."""

    command: str
    ok: bool
    value: Any = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    output: list = field(default_factory=list)
    """Log lines emitted while the command ran. Filled by the dispatcher when
    it captures output; empty otherwise."""

    @classmethod
    def success(cls, command: str, value: Any = None) -> "CommandResult":
        """A command that completed without raising."""
        return cls(command=command, ok=True, value=value)

    @classmethod
    def failure(cls, command: str, exception: BaseException) -> "CommandResult":
        """A command that raised. Captures the message and the formatted traceback."""
        return cls(
            command=command,
            ok=False,
            error=f"{type(exception).__name__}: {exception}",
            traceback=traceback.format_exc(),
        )

    @property
    def text(self) -> str:
        """
        Human-readable rendering for consoles.

        Success with no return value renders as an empty string so callers
        can decide whether to print an acknowledgement. Failure renders the
        error and, when present, the traceback.
        """
        if self.ok:
            return '' if self.value is None else str(self.value)
        if self.traceback:
            return f"Error: {self.error}\n{self.traceback}"
        return f"Error: {self.error}"

    def __str__(self) -> str:
        return self.text

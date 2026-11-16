"""
Run files: a text file of ordinary CLI commands, run in order by the `runfile` command.

A run file automates a bench sequence that would otherwise be typed by hand (jog a grating,
name the file, acquire, repeat), so a long measurement runs unattended and the same sequence
can be repeated exactly. Each line is one command, written as it would be typed at the prompt.
Blank lines and lines starting with '#' are skipped.

    # stage 1 edge walk at 800 nm
    st 800
    sg 800
    g1 -30
    g1 10
    filename s1edge_t800_g1m020
    acquire

The whole file is checked before anything moves: every line must name a command the CLI knows
(or a motor label with a whole number of steps), so a typo cannot reach the controller, which
receives any unrecognised text as a raw command. A run file cannot start another run file.

This module holds the parts that need no hardware (reading and checking the lines); the
Interface runs them (`Interface.run_command_file`), waits for each jogged motor to stop before
the next line, stops at the first command that reports an error, and writes a run log.
"""

from dataclasses import dataclass

COMMENT_PREFIX = '#'
RUN_FILE_COMMAND = 'runfile'


@dataclass(frozen=True)
class CommandLine:
    """One command from a run file, with its line number for messages."""
    line_number: int
    command: str

    @property
    def name(self):
        return self.command.split()[0].lower()

    @property
    def arguments(self):
        return self.command.split()[1:]


def read_command_lines(text):
    """The commands in a run file's text, without blank lines and comments."""
    command_lines = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        command = line.strip()
        if command and not command.startswith(COMMENT_PREFIX):
            command_lines.append(CommandLine(line_number, command))
    return command_lines


def find_invalid_lines(command_lines, command_names, motor_labels):
    """[(CommandLine, reason)] for each line the CLI would not run as a known command.

    command_names: every command name the CLI dispatches; motor_labels: the jog labels, which
    take exactly one whole number of steps. A name that is both runs as the command (the CLI
    looks commands up before motor labels), so it is not checked as a jog."""
    invalid_lines = []
    for command_line in command_lines:
        reason = _invalid_reason(command_line, command_names, motor_labels)
        if reason:
            invalid_lines.append((command_line, reason))
    return invalid_lines


def _invalid_reason(command_line, command_names, motor_labels):
    if command_line.name == RUN_FILE_COMMAND:
        return 'a run file cannot start another run file'
    if command_line.name in command_names:
        return None
    if command_line.name not in motor_labels:
        return f"'{command_line.name}' is not a command"
    if len(command_line.arguments) != 1 or not _is_whole_number(command_line.arguments[0]):
        return f"'{command_line.name}' jogs a motor: it takes one whole number of steps"
    return None


def is_motor_jog(command_line, command_names, motor_labels):
    """True when the CLI runs this line as a motor jog: a motor label that no command shares."""
    return command_line.name in motor_labels and command_line.name not in command_names


def _is_whole_number(text):
    try:
        int(text)
    except ValueError:
        return False
    return True


def reports_failure(result):
    """True when a command's result says it failed: the CLI returns ' > Error: ...' for an
    exception, and several commands return False instead of raising."""
    return result is False or (isinstance(result, str) and result.lstrip().startswith('> Error'))

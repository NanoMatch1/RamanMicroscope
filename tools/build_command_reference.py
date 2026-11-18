"""
Build docs/command_reference.md from the command docstrings.

Every command the CLI accepts comes from one of three places, looked up in this order:
the application's own commands (`Interface.interface_commands`: connections, logging, the GUI,
help), the instruments' commands (each instrument's `command_functions`, merged into
`Interface.command_map`), and the motor labels (`Microscope.motor_map`, typed with a number of
steps to jog that motor). The method's docstring is the command's documentation: `help` prints
it, and this script writes all of them into one Markdown file, with the commands that share a
method listed together. Explanations that span several commands come from the module
docstrings named in SUBSYSTEM_MODULES ("How it works" sections).

The file is generated, never edited by hand: change the docstring and re-run this script. A test
in test_headless_simulation.py fails when the file is out of date.

The file also lists what the registry cannot show by itself: command names registered in more
than one place (only the first in the lookup order runs; the file says which), and commands
that have no docstring yet.

Run:  PYTHONPATH=. python tools/build_command_reference.py           (writes the file)
      PYTHONPATH=. python tools/build_command_reference.py --check   (exit 1 if out of date)
The application is built in simulate mode to read the registry; no hardware is needed.
"""

import argparse
import contextlib
import importlib
import inspect
import io
import os
import sys
from dataclasses import dataclass

REPOSITORY_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMAND_REFERENCE_PATH = os.path.join(REPOSITORY_DIRECTORY, 'docs', 'command_reference.md')
# The line that records what the file was built from. It changes with every build, so the
# out-of-date check compares everything except this line.
BUILD_STAMP_PREFIX = '_Built from '
APPLICATION_LABEL = 'Application'
MOTORS_LABEL = 'Motors (jogging)'
# "How it works" sections: (title, module whose docstring explains it), in reading order.
SUBSYSTEM_MODULES = (
    ('PIXIS camera: live view, acquisitions, exposures', 'pixisspec.pixiscam'),
    ('Camera region of interest and binning', 'pixisspec.spectral_roi'),
    ('Stage 1 edge (g1) calibration: run files and analysis', 'filter_calibration.__main__'),
)


@dataclass(frozen=True)
class CommandRegistration:
    """One command name as one place registers it."""
    owner_label: str            # 'Application', str(instrument) or 'Motors (jogging)'
    command: str
    method: object


@dataclass(frozen=True)
class CommandSources:
    """Everything the reference is built from, read from the application (see
    sources_from_interface) or made up by a test."""
    registrations: list         # [CommandRegistration], in the CLI's lookup order
    dispatched: dict            # {command: method the CLI runs}
    motor_groups: dict          # {group name: {motor label: controller motor id}}
    subsystems: list            # [(title, explanation)]


def sources_from_interface(interface):
    """CommandSources for a built Interface, in the order _command_handler looks names up."""
    application = [CommandRegistration(APPLICATION_LABEL, command, method)
                   for command, method in interface.interface_commands.items()]
    instruments = [CommandRegistration(str(instrument), command, method)
                   for instrument in interface.registered_instruments()
                   for command, method in instrument.command_functions.items()]
    motor_groups = {group: dict(labels)
                    for group, labels in interface.microscope.action_groups.items() if labels}
    motor_labels = dict.fromkeys(label for labels in motor_groups.values() for label in labels)
    motors = [CommandRegistration(MOTORS_LABEL, label, interface.jog_motor)
              for label in motor_labels]  # a motor in two groups is still one command
    dispatched = {}
    for entry in motors:
        dispatched[entry.command] = entry.method
    dispatched.update({command: method for command, (_, method) in interface.command_map.items()})
    dispatched.update(interface.interface_commands)
    subsystems = [(title, inspect.getdoc(importlib.import_module(module_name)))
                  for title, module_name in SUBSYSTEM_MODULES]
    return CommandSources(application + instruments + motors, dispatched, motor_groups,
                          subsystems)


def _method_key(method):
    """Identity of a bound method's function and owner: aliases of one method share it."""
    return (id(getattr(method, '__self__', None)), getattr(method, '__func__', method))


def _docstring_block(method):
    docstring = inspect.getdoc(method)
    return ['```text', docstring, '```'] if docstring else ['_No docstring yet._']


def command_reference_markdown(sources, build_stamp):
    """The command reference as Markdown. build_stamp says what it was built from."""
    lines = ['# Command reference', '',
             '_Generated from the command docstrings by `tools/build_command_reference.py`; '
             'do not edit by hand. Change the docstring and re-run the script._', '',
             f'{BUILD_STAMP_PREFIX}{build_stamp}._', '',
             'Type a command and its arguments at the prompt, separated by spaces, e.g. '
             '`st 800`. `help` prints the same text; `exit` closes the camera and quits.', '']
    owner_labels = list(dict.fromkeys(entry.owner_label for entry in sources.registrations))
    for owner_label in owner_labels:
        if owner_label == MOTORS_LABEL:
            lines += _motor_lines(sources)
        else:
            lines += _owner_lines(owner_label, sources)
    for title, explanation in sources.subsystems:
        lines += [f'## How it works: {title}', '', explanation or '_No module docstring yet._', '']
    lines += _clash_lines(sources) + _undocumented_lines(sources)
    return '\n'.join(lines).rstrip('\n') + '\n'


def _owner_lines(owner_label, sources):
    lines = [f'## {owner_label}', '']
    commands_by_method = {}
    for entry in sources.registrations:
        if entry.owner_label == owner_label:
            commands_by_method.setdefault(_method_key(entry.method), []).append(entry)
    for entries in commands_by_method.values():
        method = entries[0].method
        lines += [f"### {', '.join(f'`{entry.command}`' for entry in entries)}", '']
        shadowed = [entry.command for entry in entries
                    if sources.dispatched.get(entry.command) != method]
        if shadowed:
            lines += [f'**Not reachable as {", ".join(f"`{name}`" for name in shadowed)}**: '
                      'the same name is registered earlier in the lookup order, and that one '
                      'runs.', '']
        lines += _docstring_block(method) + ['']
    return lines


def _motor_lines(sources):
    jog_method = next(entry.method for entry in sources.registrations
                      if entry.owner_label == MOTORS_LABEL)
    lines = [f'## {MOTORS_LABEL}', '', '### `<motor label> <steps>`', '']
    lines += _docstring_block(jog_method) + ['', '| Group | Motor labels (controller id) |',
                                             '|---|---|']
    for group, labels in sources.motor_groups.items():
        lines.append(f"| {group} | "
                     + ', '.join(f'`{label}` ({motor_id})' for label, motor_id in labels.items())
                     + ' |')
    return lines + ['']


def _clash_lines(sources):
    owners_by_command = {}
    for entry in sources.registrations:
        owners_by_command.setdefault(entry.command, []).append(entry)
    clashes = {command: owners for command, owners in owners_by_command.items()
               if len(owners) > 1}
    lines = ['## Command names registered more than once', '']
    if not clashes:
        return lines + ['None.', '']
    lines += ['The CLI runs one method per name: the application\'s commands first, then the '
              'instruments\' (where two instruments clash, the later one in attribute-name '
              'order), then the motor labels.', '',
              '| Command | Registered by | Runs |', '|---|---|---|']
    for command, owners in sorted(clashes.items()):
        registered_by = '; '.join(f'{entry.owner_label} (`{entry.method.__qualname__}`)'
                                  for entry in owners)
        lines.append(f'| `{command}` | {registered_by} | '
                     f'`{sources.dispatched[command].__qualname__}` |')
    return lines + ['']


def _undocumented_lines(sources):
    undocumented = sorted(command for command, method in sources.dispatched.items()
                          if not inspect.getdoc(method))
    lines = ['## Commands without a docstring', '']
    if not undocumented:
        return lines + ['None.', '']
    return lines + [', '.join(f'`{command}`' for command in undocumented), '']


def without_build_stamp(markdown):
    """The reference minus its stamp line, for comparing two builds."""
    return '\n'.join(line for line in markdown.split('\n')
                     if not line.startswith(BUILD_STAMP_PREFIX))


def describe_build(repository_directory=REPOSITORY_DIRECTORY):
    """'git <commit> on <branch>[, with uncommitted changes]' for the stamp line."""
    sys.path.insert(0, repository_directory)
    from wavelength_calibration.provenance import software_version
    version = software_version(repository_directory)
    commit = (version.get('commit') or 'unknown')[:7]
    stamp = f"git {commit} on {version.get('branch') or 'unknown branch'}"
    return stamp + (', with uncommitted changes' if version.get('uncommitted_changes') else '')


def reference_for_interface(interface, build_stamp):
    """The command reference for a built Interface."""
    return command_reference_markdown(sources_from_interface(interface), build_stamp)


def build_simulated_interface():
    """The application in simulate mode, with its start-up chatter and any prompt suppressed."""
    sys.path.insert(0, REPOSITORY_DIRECTORY)
    sys.stdin = io.StringIO()
    from interface_run_me import Interface
    with contextlib.redirect_stdout(io.StringIO()):
        return Interface(simulate=True, com_port='COM10', debug_skip=[])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--check', action='store_true',
                        help='exit 1 if docs/command_reference.md is out of date; write nothing')
    arguments = parser.parse_args(argv)
    markdown = reference_for_interface(build_simulated_interface(), describe_build())
    if arguments.check:
        try:
            with open(COMMAND_REFERENCE_PATH) as file:
                current = file.read()
        except FileNotFoundError:
            current = ''
        up_to_date = without_build_stamp(current) == without_build_stamp(markdown)
        print(f"{COMMAND_REFERENCE_PATH} is {'up to date' if up_to_date else 'OUT OF DATE'}")
        return 0 if up_to_date else 1
    with open(COMMAND_REFERENCE_PATH, 'w') as file:
        file.write(markdown)
    print(f"Wrote {COMMAND_REFERENCE_PATH}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

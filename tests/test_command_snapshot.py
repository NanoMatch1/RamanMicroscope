import json
import os
import pytest

from interface_run_me import Interface

SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), 'command_snapshot.json')


def get_current_commands():
    interface = Interface(simulate=True, com_port='COM_TEST', baud=9600, debug_skip=['camera'])
    # Build a simple dict of command -> owning instrument class name
    snapshot = {name: inst.__class__.__name__ for name, (inst, method) in interface.command_map.items()}
    return snapshot


def test_command_set_stable():
    current = get_current_commands()
    if not os.path.exists(SNAPSHOT_FILE):
        # First run creates the snapshot (developer must review & commit)
        with open(SNAPSHOT_FILE, 'w') as f:
            json.dump(current, f, indent=2, sort_keys=True)
        pytest.skip('Created initial command snapshot; validate and re-run tests.')
    else:
        with open(SNAPSHOT_FILE, 'r') as f:
            saved = json.load(f)
        # Compare keys only for now (owner changes acceptable in Phase 1)
        assert set(current.keys()) == set(saved.keys()), 'Command set changed unexpectedly. Review refactor.'

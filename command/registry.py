"""Command discovery and registry utilities.

Phase 1 extraction: provides the same dynamic command map generation that
Interface._generate_command_map previously performed, but encapsulated here
for clarity and future extension (namespacing, metadata, validation).

Backwards compatibility: build_command_map replicates the old behaviour of
flattening all Instrument.command_functions dicts.
"""
from __future__ import annotations
import inspect
from typing import Dict, Tuple, Any

try:
    from instruments.instrument_base import Instrument as InstrumentBase
except Exception:  # pragma: no cover - fallback for early refactor stages
    InstrumentBase = object  # type: ignore

try:
    from instruments_old import Instrument  # legacy base
except Exception:  # pragma: no cover
    Instrument = object  # type: ignore

# Attribute set by the ui_callable decorator to expose commands
UI_ATTR = "is_ui_process_callable"


def is_instrument(obj: Any) -> bool:
    return isinstance(obj, (Instrument, InstrumentBase))


def discover_instruments(interface_obj: Any):
    """Yield instrument-like attributes from an interface instance.

    Mirrors the previous comprehension inside _generate_command_map.
    """
    for attr in dir(interface_obj):
        try:
            value = getattr(interface_obj, attr)
        except Exception:
            continue
        if is_instrument(value):
            yield value


def build_command_map(*providers: Any) -> Dict[str, Tuple[Any, Any]]:
    """Build a command map from one or more instrument-like providers.

    Each provider must expose a .command_functions dict mapping command string
    to callables. This preserves existing structure. Returns a dict:
        command_name -> (provider_instance, bound_method)
    Collisions: later providers override earlier ones (same as old implicit behaviour).
    """
    command_map: Dict[str, Tuple[Any, Any]] = {}
    for provider in providers:
        cf = getattr(provider, 'command_functions', None)
        if not isinstance(cf, dict):
            continue
        for name, method in cf.items():
            command_map[name] = (provider, method)
    return command_map


def discover_ui_callables(obj: Any):
    """Discover methods decorated with ui_callable on an object.

    Not yet used in Phase 1, but will enable Phase 2 where we may auto-build
    command_functions instead of maintaining it manually inside Microscope.
    """
    for name, member in inspect.getmembers(obj):
        if callable(member) and getattr(member, UI_ATTR, False):
            yield name, member

__all__ = [
    'build_command_map',
    'discover_instruments',
    'discover_ui_callables',
]

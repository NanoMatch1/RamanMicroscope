"""MotionService

Thin façade around low-level controller communication for motion-related
commands. Phase 2B initial extraction: isolates command length splitting
so higher layers (controller / interface) can delegate and we can evolve
segmentation rules & add validation without touching hardware code.

Non-goal: change behaviour. Logic copied from ArduinoMEGA._format_command_length.
"""
from __future__ import annotations
from typing import List

class MotionService:
    """Utility / stateless style service for formatting controller motion commands.

    Currently only exposes command segmentation. Future additions may include:
    - batching move & read commands with dependency ordering
    - validation of motor identifiers
    - coordinate transforms (user units -> steps)
    """

    def __init__(self, threshold: int = 56):
        self.threshold = threshold

    def segment(self, command: str) -> List[str]:
        """Return list of command segments within controller buffer threshold.

        Validation added even for short commands (stricter than legacy helper):
        - matching start/end delimiter
        - allowed delimiter set
        """
        if not command:
            raise ValueError("Command must be non-empty.")

        if command[0] != command[-1]:
            raise ValueError("Command must start and end with the same delimiter.")

        if command[0] not in ['o', 'g', 'c', 's', 'm']:
            raise ValueError("Command must start with 'o', 'g', 'c', 's', or 'm'.")

        threshold = self.threshold
        if len(command) <= threshold:
            return [command]

        delimiter = command[0]
        inner = command[1:-1]
        tokens = inner.split()
        segments: List[str] = []
        current_tokens: List[str] = []

        for token in tokens:
            projected = len(' '.join(current_tokens + [token]))
            if projected + 2 > threshold:  # +2 for delimiters
                segment = delimiter + ' '.join(current_tokens) + delimiter
                segments.append(segment)
                current_tokens = [token]
            else:
                current_tokens.append(token)

        if current_tokens:
            segment = delimiter + ' '.join(current_tokens) + delimiter
            segments.append(segment)

        return segments

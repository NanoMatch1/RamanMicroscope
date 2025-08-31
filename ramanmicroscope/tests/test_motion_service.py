import pytest
from ramanmicroscope.subsystems import MotionService


def test_segment_short_command_no_split():
    svc = MotionService(threshold=20)
    cmd = 'gM1g'
    assert svc.segment(cmd) == ['gM1g']


def test_segment_splits_long_command():
    svc = MotionService(threshold=12)
    inner_tokens = ['M1', 'M2', 'M3', 'M4', 'M5']
    cmd = 'g' + ' '.join(inner_tokens) + 'g'
    parts = svc.segment(cmd)
    # Validate each part has proper delimiters and under threshold
    for part in parts:
        assert part[0] == 'g' and part[-1] == 'g'
        assert len(part) <= 12
    # Reconstruct token list
    reconstructed = []
    for part in parts:
        reconstructed.extend(part[1:-1].split())
    assert reconstructed == inner_tokens


def test_invalid_delimiter_raises():
    svc = MotionService()
    with pytest.raises(ValueError):
        svc.segment('xABCx')


def test_mismatched_delimiters_raises():
    svc = MotionService()
    with pytest.raises(ValueError):
        svc.segment('gABCc')


def test_wrapper_equivalence_with_controller():
    from ramanmicroscope.controller import ArduinoMEGA

    class _StubInterface:
        def __init__(self):
            from ramanmicroscope.logging_utils import LoggerInterface
            self.logger = LoggerInterface('stub')
            self.simulate = True
    stub = _StubInterface()
    controller = ArduinoMEGA(interface=stub, simulate=True)
    long_cmd = 'g' + ' '.join(['M{}'.format(i) for i in range(10)]) + 'g'
    assert controller._format_command_length(long_cmd) == MotionService().segment(long_cmd)

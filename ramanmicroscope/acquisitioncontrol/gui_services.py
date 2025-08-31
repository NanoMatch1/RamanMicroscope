# gui_emitter_service.py
from PyQt5.QtCore import QObject, pyqtSignal

class GUIEmitterService(QObject):
    """
    Centralized Qt signals for all GUI updates.
    Hardware and controller layers get a reference to this service
    and call its methods to emit data back to the UI.
    """

    # define all signals once here
    laser_power_changed = pyqtSignal(float)     # (power_level,)
    laser_status = pyqtSignal(bool)          # (is_on,)

    def __init__(self, interface, parent=None):
        super().__init__(parent)
        self.interface = interface

    # === wrapper methods to keep callers clean ===

    def update_laser_power(self, power_level):
        """Emit new laser power level."""
        self.laser_power_changed.emit(power_level)

    def update_laser_status(self, is_on):
        """Emit new laser status."""
        self.laser_status.emit(is_on)

    # … add other emitters as needed

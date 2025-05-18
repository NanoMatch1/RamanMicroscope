from abc import ABC, abstractmethod
from instruments.instrument_base import Instrument

class Camera(Instrument, ABC):
    """
    Abstract base class for all laser instruments. Defines the required interface and
    registers UI-callable commands for interactive control.
    """
    def __init__(self):
        super().__init__()
        # Child classes will populate self.command_functions via @ui_callable registration

    @abstractmethod
    def open_stream(self):
        '''Opens the camera stream. Needs to be run before grabbing a frame.'''
        pass
    
    @abstractmethod
    def grab_frame(self):
        """Grabs a single frame from the camera stream and returns it."""
        pass

    @abstractmethod
    def close_stream(self):
        """Closes the camera stream. Should be called when done with the camera."""
        pass

    @abstractmethod
    def initialise(self):
        """Initializes the camera. Should be called before any other methods."""
        pass

    @abstractmethod
    def close_camera(self):
        """Closes the camera connection. Should be called when done with the camera."""
        pass

    @abstractmethod
    def start_continuous_acquisition(self):
        """Starts continuous acquisition for live view."""
        pass

    @abstractmethod
    def stop_continuous_acquisition(self):
        """Stops continuous acquisition."""
        pass

    @abstractmethod
    def set_exposure_time(self, exposure_time):
        """Sets the camera's exposure time."""
        pass
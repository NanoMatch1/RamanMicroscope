import threading
import time
from ..util_decorators import interface_locked

class LaserWatchdog:
    def __init__(self, interface, timeout_seconds=600, showdown_timeout_multiplier=3):
        """Timeout is in seconds, default is 10 minutes.
        shutdown_timeout_multiplier is how many times the timeout is multiplied to trigger a hard shutdown."""
        self.interface = interface
        self.timeout = timeout_seconds
        self.showdown_timeout_multiplier = showdown_timeout_multiplier
        self._lock = threading.Lock()
        self._last_heartbeat = time.time()

        self._active = False
        self._thread = None
        self._thread_lock = threading.Lock()

    def start(self):
        """Start or restart the watchdog thread."""
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return  # Already running

            self._active = True
            self._last_heartbeat = time.time()
            self._thread = threading.Thread(target=self._watch, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the watchdog safely."""
        with self._thread_lock:
            self._active = False
            current = threading.current_thread()
            if self._thread and self._thread.is_alive() and self._thread != current:
                self._thread.join()
            self._thread = None

    def is_running(self):
        """Return True if the watchdog thread is currently active and alive."""
        with self._thread_lock:
            return self._active and self._thread is not None and self._thread.is_alive()

    def heartbeat(self):
        """Reset the inactivity timer."""
        with self._lock:
            self._last_heartbeat = time.time()

    def _watch(self):
        while self._active:
            with self._lock:
                elapsed = time.time() - self._last_heartbeat

            if self.interface.laser.current_power > 0.05:
                if elapsed > self.timeout:
                    self.power_down()

            if elapsed > self.timeout * self.showdown_timeout_multiplier:
                self.default_shutdown()
                self._active = False  # triggers exit from while loop

            time.sleep(1)

    @interface_locked
    def power_down(self):
        """Soft power-down to minimum state."""
        self.interface.logger.info("\n[Watchdog] Inactivity timeout reached. Laser set to idle.")
        self.interface.laser.set_power(0.05)

    @interface_locked
    def default_shutdown(self):
        """Hard laser shutdown."""
        self.interface.logger.info("\n[Watchdog] Max inactivity exceeded. Laser turned OFF.")
        self.interface.laser.turn_off()

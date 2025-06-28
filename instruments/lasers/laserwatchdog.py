import threading
import time
import instruments.util_decorators.interface_locked
# from instruments.instrument_base import interface_locked

class LaserWatchdog:
    def __init__(self, interface, timeout_seconds=300, shutdown_callback=None):
        self.interface = interface
        self.timeout = timeout_seconds
        self.shutdown_callback = shutdown_callback or self.default_shutdown
        self._lock = threading.Lock()
        self._last_heartbeat = time.time()
        self._active = True

        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def heartbeat(self):
        """Call this method to reset the inactivity timer."""
        with self._lock:
            self._last_heartbeat = time.time()

    def _watch(self):
        while self._active:
            with self._lock:
                elapsed = time.time() - self._last_heartbeat
            if elapsed > self.timeout:
                self.power_down()
                self._active = False
            time.sleep(1)

    def stop(self):
        """Stop the watchdog manually (e.g., if program exits normally)."""
        self._active = False
        self._thread.join()

    @interface_locked
    def power_down(self):
        '''Soft power decrease to minimum power state.'''
        self.interface.laser.set_power(0.05)
        self.interface.logger.info("[Watchdog] Inactivity timeout reached. Laser set to idle.")


    @interface_locked
    def default_shutdown(self):
        """Override or pass your own shutdown logic."""
        self.interface.laser.turn_off()
        self.interface.logger.info("[Watchdog] No activity time exceeded: Laser has been turned OFF.")
        # Insert actual laser turn-off code here

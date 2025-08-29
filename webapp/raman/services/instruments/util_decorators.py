def ui_callable(func):
    """
    Decorator that marks a method as UI-callable by
    setting a custom attribute on the function object.
    """
    func.is_ui_process_callable = True
    return func

def interface_locked(method):
    """ Decorator which allows any method to respect the interface lock, without having to code it in every method. """
    def wrapper(self, *args, **kwargs):
        lock = getattr(getattr(self, 'interface', None), 'lock', None)
        if lock is None:
            raise AttributeError(f"{self.__class__.__name__} does not have 'interface.lock'")
        with lock:
            return method(self, *args, **kwargs)
    return wrapper

def heartbeat(method):
    """
    Decorator to ensure that a method updates the laser's heartbeat.
    This is used to keep the laser watchdog active.
    """
    def wrapper(self, *args, **kwargs):
        heartbeat = getattr(getattr(self, 'interface', None), 'heartbeat', None) or getattr(self, 'heartbeat', None)
        if heartbeat is None:
            raise AttributeError(f"{self.__class__.__name__} does not have 'interface.heartbeat', check if the interface is initialised correctly.")
        
        heartbeat()  # Update the heartbeat to keep the watchdog active
        return method(self, *args, **kwargs)
    return wrapper
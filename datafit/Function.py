import numpy as np
from abc import ABC, abstractmethod


# ── Local Gaussian implementation ─────────────────────────────────────────────
# Replaces the missing analysis_spectroscopy.data_processing.datafit.functions
# import. Provides a drop-in FitFunction subclass for a Gaussian peak.
# ── END ───────────────────────────────────────────────────────────────────────

class FitFunction(ABC):

    optimise = True
    _params  = []
    _bounds  = []

    def __init__(self, bounds):
        if not bounds:
            bounds = self._defaultBounds
        self.set_bounds(bounds)

    def get_num_params(self):
        return self._numParams

    def set_params(self, params):
        self._params = list(params)
        return self

    def get_params(self):
        return self._params

    def set_bounds(self, bounds):
        bounds_min = []
        bounds_max = []
        for b in bounds:
            bounds_min += [b[0]]
            bounds_max += [b[1]]
        self._bounds = [bounds_min, bounds_max]
        return self

    def get_bounds(self):
        return self._bounds

    def set_optimise(self, optimise):
        self.optimise = optimise
        return self

    @abstractmethod
    def build_function(self, x):
        raise NotImplementedError


class gaussian(FitFunction):
    """Single Gaussian peak: amp * exp(-0.5 * ((x - pos) / width)^2)"""

    _numParams    = 3
    _defaultBounds = [
        (-np.inf, np.inf),   # position
        (0,       np.inf),   # amplitude
        (1e-6,    np.inf),   # width (sigma)
    ]

    def __init__(self, position, amplitude, width, bounds=None):
        self._params = [position, amplitude, width]
        super().__init__(bounds or self._defaultBounds)

    def set_params(self, params):
        self._params = list(params)
        return self

    def get_params(self):
        return self._params

    def build_function(self, x):
        pos, amp, width = self._params
        return amp * np.exp(-0.5 * ((x - pos) / width) ** 2)


class lorentzian(FitFunction):
    """Single Lorentzian peak: amp * (width^2 / ((x - pos)^2 + width^2))"""

    _numParams     = 3
    _defaultBounds = [
        (-np.inf, np.inf),
        (0,       np.inf),
        (1e-6,    np.inf),
    ]

    def __init__(self, position, amplitude, width, bounds=None):
        self._params = [position, amplitude, width]
        super().__init__(bounds or self._defaultBounds)

    def set_params(self, params):
        self._params = list(params)
        return self

    def get_params(self):
        return self._params

    def build_function(self, x):
        pos, amp, width = self._params
        return amp * (width ** 2 / ((x - pos) ** 2 + width ** 2))


# ── Factory ───────────────────────────────────────────────────────────────────

_FUNCTION_REGISTRY = {
    'gaussian':   gaussian,
    'lorentzian': lorentzian,
}

class FitFunctionFactory(object):
    def __new__(cls, function, *args, **kwargs):
        name = function.lower()
        if name not in _FUNCTION_REGISTRY:
            print(f"Error: unknown fit function '{function}'. "
                  f"Available: {list(_FUNCTION_REGISTRY.keys())}")
            return None
        return _FUNCTION_REGISTRY[name](*args, **kwargs)

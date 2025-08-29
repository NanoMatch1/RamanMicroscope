import importlib
from abc import ABC, abstractmethod

class FitFunctionFactory(object):
    def __new__(self,function,*args,**kwargs):
        FitFunction = None
        try:
            module = importlib.import_module('.functions.{}'.format(function), 'analysis_spectroscopy.data_processing.datafit')
            FitFunction = getattr(module, function)(*args,**kwargs)

        except ImportError as error:
            print('Error importing data fit function: ' + function + '\nError: ' + repr(error))

        return FitFunction

class FitFunction(ABC):

    optimise = True
    _params = []
    _bounds = []

    def __init__(self,bounds):
        if not bounds:
            bounds = self._defaultBounds
        self.set_bounds(bounds)

    def get_num_params(self):
        return self._numParams

    def set_params(self,params):
        self._params = params
        return self

    def get_params(self):
        return self._params

    def set_bounds(self,bounds):
        bounds_min = []
        bounds_max = []
        for b in bounds:
            bounds_min += [b[0]]
            bounds_max += [b[1]]
        self._bounds = [bounds_min,bounds_max]
        return self

    def get_bounds(self):
        return self._bounds

    def set_optimise(self,optimise):
        self.optimise = optimise
        return self

    @abstractmethod
    def set_params(self,params): raise NotImplementedError

    @abstractmethod
    def get_params(self,params): raise NotImplementedError

    @abstractmethod
    def build_function(self): raise NotImplementedError
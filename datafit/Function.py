import os
import importlib
from abc import ABC, abstractmethod

class FitFunctionFactory:
    def __new__(self, function_name, *args, **kwargs):
        try:
            # Dynamically search for the function in the functions folder
            functions_dir = os.path.join(os.path.dirname(__file__), 'functions')
            for file in os.listdir(functions_dir):
                if file.endswith('.py') and not file.startswith('__init__'):
                    module_name = file[:-3]  # Remove .py extension
                    module_path = f"{__package__}.functions.{module_name}"
                    module = importlib.import_module(module_path)

                    # Check if the function exists in the module
                    if hasattr(module, function_name):
                        FunctionClass = getattr(module, function_name)
                        return FunctionClass(*args, **kwargs)

            raise ImportError(f"Function '{function_name}' not found in any module in the functions folder.")

        except ImportError as error:
            print(f"Error importing data fit function: {function_name}\nError: {repr(error)}")
            return None

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
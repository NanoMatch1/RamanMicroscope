import numpy as np
from ..Function import FitFunction

class constant(FitFunction):
    _numParams = 1
    _defaultBounds = [[-float('inf'),float('inf')]]

    def __init__(self, height, bounds=None):
        FitFunction.__init__(self,bounds)
        self.set_params([height])

    def set_params(self, params):
        self.__height = params[0]
        return self

    def get_params(self):
    	return [self.__height]
    
    def build_function(self,x):
        x = np.array(x)
        y = np.zeros_like(x) + self.__height
        return y
import numpy as np
from ..Function import FitFunction

class power(FitFunction):
    _numParams = 2
    _defaultBounds = [[-float('inf'),float('inf')],
                    [-float('inf'),float('inf')]]

    def __init__(self, power, scale, bounds=None):
        FitFunction.__init__(self,bounds)
        self.set_params([power, scale])

    def set_params(self, params):
        self.__power = params[0]
        self.__scale = params[1]
        return self

    def get_params(self):
    	return [self.__power,self.__scale]

    def build_function(self,x):
        x = np.array(x).astype(float)
        y = self.__scale * np.power(x,float(self.__power))
        return y
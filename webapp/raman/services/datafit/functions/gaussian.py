import numpy as np
from ..Function import FitFunction

class gaussian(FitFunction):
    _numParams = 3
    _defaultBounds = [[0,float('inf')],
                    [0,float('inf')],
                    [0,float('inf')]]

    def __init__(self, position, amplitude, width, bounds=None):
        FitFunction.__init__(self,bounds)
        self.set_params([position, amplitude, width])

    def set_params(self, params):
        self.__position = params[0]
        self.__amplitude = params[1]
        self.__width = params[2]
        return self

    def get_params(self):
    	return [self.__position,self.__amplitude,self.__width]

    def build_function(self,x):
        x = np.array(x)
        y = self.__amplitude * np.exp( -((x - self.__position)/self.__width)**2)
        return y
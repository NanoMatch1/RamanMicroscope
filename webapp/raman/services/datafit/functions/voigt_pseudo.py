import numpy as np
from ..Function import FitFunction

class voigt_pseudo(FitFunction):
    _numParams = 4
    _defaultBounds = ((0,float('inf')),
                    (0,float('inf')),
                    (0,float('inf')),
                    (0,1))

    def __init__(self, position, amplitude, width, bounds):
        FitFunction.__init__(self,bounds)
        self.set_params([position, amplitude, width, 0.5])
        if bounds:
            bounds.append([0,1])
            self.set_bounds(bounds)

    def set_params(self, params):
        self.__position = params[0]
        self.__amplitude = params[1]
        self.__width = params[2]
        self.__eta = params[3]
        return self

    def get_params(self):
    	return [self.__position,self.__amplitude,self.__width,self.__eta]

    def build_function(self,x):
        x = np.array(x)
        y = self.__amplitude * ( self.__eta * (1 / (1 + np.power(((x - self.__position)/ self.__width),2))) + (1 - self.__eta) * (np.exp( -((x - self.__position)/self.__width)**2)) )

        return y

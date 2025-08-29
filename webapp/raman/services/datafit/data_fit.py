import csv
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from .Function import FitFunctionFactory

class data_fit():

	def __init__(self):
		self.__data_x = None
		self.__data_y = None
		self.__functions = []
		self.__optimise_params = []
		self.__optimise_bounds = []

	def set_data(self, data):
		data = np.array(data)
		self.__data_x = data[:,0]
		self.__data_y = data[:,1]
		return self

	def check_data_set(self):
		if self.__data_x is None:
			raise RuntimeError("__data_x is not set")
		if self.__data_y is None:
			raise RuntimeError("__data_y is not set")


	def add_function(self, function, *args, **kwargs):
		self.__functions.append(FitFunctionFactory(function, *args, **kwargs))

	def get_optimise_params(self):
		optimise_params = []
		optimise_bounds_min = []
		optimise_bounds_max = []
		for function in self.__functions:
			if function.optimise:
				optimise_params += function.get_params()
				optimise_bounds_min += function.get_bounds()[0]
				optimise_bounds_max += function.get_bounds()[1]
		self.__optimise_params = optimise_params
		self.__optimise_bounds = [optimise_bounds_min, optimise_bounds_max]
		return tuple(optimise_params)

	def update_function_params(self,params):
		for function in self.__functions:
			function_params, params = np.split(params,[function.get_num_params()])
			function.set_params(function_params)

	def optimise(self,**kwargs):
		self.check_data_set()
		self.get_optimise_params()
		popt, pcov = curve_fit(self.build_fit , self.__data_x, self.__data_y, p0=self.get_optimise_params(), bounds=self.__optimise_bounds, **kwargs)
		# popt, pcov = curve_fit(self.build_fit , self.__data_x, self.__data_y, p0=[1,1,1])
		self.update_function_params(popt)

	def build_fit(self, x, *params):
		self.update_function_params(params)
		y = np.zeros_like(x)
		for function in self.__functions:
			y += function.build_function(x)
		return y

	def get_residual(self):
		return self.__data_y - self.build_fit(self.__data_x, *self.get_optimise_params())


	def plot_data(self,show=True):
		self.check_data_set()
		plt.plot(self.__data_x,self.__data_y)
		if show:
			plt.show()

	def plot_functions(self,show=True):
		self.check_data_set()
		for function in self.__functions:
			plt.plot(self.__data_x,function.build_function(self.__data_x))
		if show:
			plt.show()

	def plot_functions_subplot(self,ax = 111,show=True):
		self.check_data_set()
		for function in self.__functions:
			plt.subplot(ax)
			plt.plot(self.__data_x,function.build_function(self.__data_x), color)
		if show:
			plt.show()

	def plot_fit(self, show=True):
		self.check_data_set()
		plt.plot(self.__data_x,self.build_fit(self.__data_x, *self.get_optimise_params()))
		if show:
			plt.show()

	def plot_residual(self,show=True):
		self.check_data_set()
		plt.plot(self.__data_x,self.get_residual())
		if show:
			plt.show()

	def save_plot(self,fileLocation):
		plt.savefig('{}.pdf'.format(fileLocation), format='pdf', dpi=1200)
		plt.savefig('{}.png'.format(fileLocation), dpi=1200)

	def get_functions(self):
		result = []
		for function in self.__functions:
				result.append([type(function).__name__] + function.get_params())

		return result

	def check_functions(self):
		print('params, functions, bounds')
		for param in self.__optimise_params:
			print(param)
		for function in self.__functions:
			print(function)
		for bound in self.__optimise_bounds:
			print(bound)

	def reset_functions(self):
		self.__functions = []
		self.__optimise_params = []
		self.__optimise_bounds = []

	def save_functions(self,fileLocation):
		with open('{}'.format(fileLocation), 'w', newline='') as file:
			writer = csv.writer(file, delimiter=',',
									quotechar='|', quoting=csv.QUOTE_MINIMAL)
			for function in self.__functions:
				writer.writerow([type(function).__name__] + function.get_params())

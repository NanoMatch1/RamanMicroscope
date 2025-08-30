import numpy as np
from .data_fit import data_fit

class Peak:

    def __init__(self, position, amplitude, width, peak_type='gaussian'):
        self.pos = position
        self.amp = amplitude
        self.width = width
        self.peak_type = peak_type

    def __repr__(self):
        return f"Peak(type={self.peak_type}, pos={self.position:.2f}, amp={self.amplitude:.2f}, width={self.width:.2f})"

class AutoPeakFitter:
    def __init__(self, dataX, dataY,
                 peak_type='gaussian',
                 peak_sign='positive',
                 ftol=1e-4, gtol=1e-4, xtol=1e-4,
                 show_plot=False):
        
        self.dataY = dataY
        self.dataX = dataX
        self.peak_type = peak_type.lower()
        self.peak_sign = peak_sign
        self.ftol, self.gtol, self.xtol = ftol, gtol, xtol


        self.Fit = data_fit()
        self.peaks = []
        self.peakfit_list = []

    def package_peaks(self, peak_list):
        '''Convert the list of peaks into a list of Peak objects.'''
        peak = peak_list[0]
        return Peak(*peak[1:4], peak_type=peak[0])

    def add_initial_peak(self, peak_index):
        """Add a single peak guess using a dataX index."""
        peak_pos = self.dataX[peak_index]
        amp = self.dataY[peak_index]
        data_range = self.dataX[-1] - self.dataX[0]

        # Estimate width (fallback = 1% of X range)
        half_max = amp / 2
        left = np.where(self.dataY[:peak_index] < half_max)[0]
        right = np.where(self.dataY[peak_index:] < half_max)[0]

        if left.size > 0 and right.size > 0:
            fwhm = self.dataX[peak_index + right[0]] - self.dataX[left[-1]]
        else:
            fwhm = data_range / 100

        self.peaks.append([
            self.peak_type,
            [peak_pos, self.dataX[0], self.dataX[-1]],                       # position + bounds
            [amp, np.min(self.dataY), np.max(self.dataY) * 2],              # amplitude + bounds
            [fwhm, data_range / 5000, data_range / 10]                        # width + bounds
        ])

    def setup_fit(self):
        self.Fit.reset_functions()
        self.Fit.set_data(np.column_stack((self.dataX, self.dataY)))

        for peak in self.peaks:
            name, posB, ampB, wB = peak
            args = [posB[0], ampB[0], wB[0]]
            bounds = [posB[1:], ampB[1:], wB[1:]]
            self.Fit.add_function(name, *args, bounds=bounds)

    def optimise(self):
        self.setup_fit()
        self.Fit.optimise(ftol=self.ftol, gtol=self.gtol, xtol=self.xtol, maxfev=100000)
        self.peakfit_list = self.Fit.get_functions()

    def run(self, initial_index=None):
        """Run the full peak fit given an index guess."""

        if initial_index is None:
            initial_index = np.argmax(self.dataY)
        self.add_initial_peak(int(initial_index))
        self.optimise()
        peak = self.package_peaks(self.peakfit_list)
        self.peaks = []  # Clear peaks for next fit

        return peak
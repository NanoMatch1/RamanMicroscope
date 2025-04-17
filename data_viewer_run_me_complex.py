import numpy as np
import matplotlib.pyplot as plt
import os
import time
import threading
import tkinter as tk
import zipfile

import traceback
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import RectangleSelector


class LiveDataPlotter:
    def __init__(self, image_name, wavelengths, dataDir, **kwargs):
        self.dataDir = dataDir
        self.image_file_path = os.path.join(self.dataDir, image_name)
        self.wavelengths_file_path = os.path.join(self.dataDir, wavelengths)
        self.autoscale_enabled = True
        self.updating = True
        self.roi = None  # Region of Interest for autoscaling
        self.y_center_entry = kwargs.get('bin_center', 70)
        self.y_width_entry = kwargs.get('bin_width', 10)

        self.data = np.zeros((10, 10))
        self.wavelength_axis = np.arange(self.data.shape[1])

        self.data_mode = "Image"
        self.data_mode = "Spectrum"
        self.spectrum_roi = (50,1100)
        self.plot_limits = (700,900)

        self.image_limits = (None, None)

        self.bin_height = kwargs.get("bin_height", 0)  # Default bin height


        # Initialize Tkinter and Matplotlib
        self.root = tk.Tk()
        self.root.title("Live Data Plotter")

        # build your figure/canvas exactly once
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot([], [], 'r-')
        self.vline = self.ax.axvline(0, color='blue')
        # force origin='lower' so Y goes up
        self.im = self.ax.imshow(
            np.zeros((10,10)),
            cmap='plasma',
            vmin=0, vmax=1,
            origin='lower'
        )
        self._build_canvas()

        # Set up the initial image display
        self.im = self.ax.imshow(np.zeros((10,10)), cmap='plasma', vmin=0, vmax=1)
        
        self.cursor_label = tk.Label(self.root, text="X: --, Y: --, Intensity: --")
        self.cursor_label.pack(side=tk.BOTTOM)
        self.fig.canvas.mpl_connect("motion_notify_event", self.update_cursor)

        self.fig.canvas.mpl_connect("scroll_event", self.zoom)
        self.zoom_limits = None  # Store zoom range
        # Set up a Tkinter canvas for Matplotlib
        # self._build_canvas()

        # Create control buttons and entry fields
        self.create_controls()

        # Start background threads to monitor the files and update the plot
        self.monitor_image_thread = threading.Thread(target=self.monitor_image_file, daemon=True)
        self.monitor_image_thread.start()

        self.monitor_wavelength_thread = threading.Thread(target=self.monitor_wavelength_file, daemon=True)
        self.monitor_wavelength_thread.start()
        
        
        self.apply_y_roi()

    def _safe_update_spectrum(self, data):
        if data is None:
            return

        x, y = data[:, 0], data[:, 1]
        self.line.set_data(x, y)
        idx = min(50, x.size - 1)
        self.vline.set_xdata(x[idx])

        # lock X limits to full wavelength span
        self.ax.set_xlim(x[0], x[-1])

        if self.autoscale_enabled:
            if self.roi:
                y0, y1 = self.roi
                y_roi = y[y0:y1]
                if y_roi.size:
                    self.ax.set_ylim(y_roi.min(), y_roi.max())
            else:
                # recompute data limits then autoscale only Y
                self.ax.relim()
                self.ax.autoscale_view(scalex=False, scaley=True)

        self.canvas.draw_idle()

    def _safe_update_image(self, frame):
        # frame is 2D
        self.im.set_data(frame)
        if self.image_autoscale_enabled:
            self.im.set_clim(frame.min(), frame.max())

        # restore any zoom limits
        if self.zoom_limits:
            xlim, ylim = self.zoom_limits
            self.ax.set_xlim(xlim)
            self.ax.set_ylim(ylim)

        # make *sure* we still have origin='lower'
        self.im.set_origin('lower')

        self.canvas.draw_idle()

    def zoom(self, event):
        """ Zooms in/out using the mouse scroll wheel. """
        if event.inaxes is None or self.data_mode != "Image":
            return

        scale_factor = 1.2 if event.step > 0 else 0.8  # Scroll up = zoom in, Scroll down = zoom out

        # Get current limits
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        # Zoom by scaling limits
        x_center, y_center = (xlim[0] + xlim[1]) / 2, (ylim[0] + ylim[1]) / 2
        new_xlim = [x_center + (x - x_center) * scale_factor for x in xlim]
        new_ylim = [y_center + (y - y_center) * scale_factor for y in ylim]

        # Apply new limits
        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)

        # Save zoom state
        self.zoom_limits = (new_xlim, new_ylim)
        self.canvas.draw()


    def update_cursor(self, event):
        """ Track mouse movement and update the cursor label. """
        if event.inaxes is None or self.data_mode != "Image":
            return

        x, y = int(event.xdata), int(event.ydata)
        
        if 0 <= x < self.data.shape[1] and 0 <= y < self.data.shape[0]:
            intensity = self.data[y, x]
            self.cursor_label.config(text=f"X: {x}, Y: {y}, Intensity: {intensity}")

    
    def _build_canvas(self):
        """Call this exactly once in __init__."""
        # assume self.fig and self.ax were created in __init__
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.draw_idle()


    def toggle_data_mode(self):
        """Switch between image and spectrum by hiding/showing artists."""
        if self.data_mode == "Image":
            self.data_mode = "Spectrum"
            # hide image
            self.im.set_visible(False)
            # show line + vline
            self.line.set_visible(True)
            self.vline.set_visible(True)
            # update spectrum immediately
            spec = self.frame_to_spectrum()
            self._safe_update_spectrum(spec)

        else:
            self.data_mode = "Image"
            # hide spectrum artists
            self.line.set_visible(False)
            self.vline.set_visible(False)
            # show image
            self.im.set_visible(True)
            # update image immediately
            self._safe_update_image(self.data)

        # update title & button text
        self.ax.set_title(self.data_mode)
        self.data_mode_button.config(text=self.data_mode)
        self.canvas.draw_idle()


    def create_controls(self):
        # Create a frame for buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Autoscale toggle button
        autoscale_button = tk.Button(button_frame, text="Toggle Autoscale", command=self.toggle_autoscale)
        autoscale_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Start/Stop button for updating
        self.update_button = tk.Button(button_frame, text="Start/Stop Update", command=self.toggle_update)
        self.update_button.pack(side=tk.LEFT, padx=5, pady=5)

        # ROI selection for autoscale
        tk.Label(button_frame, text="ROI Start:").pack(side=tk.LEFT)
        self.roi_start = tk.Entry(button_frame, width=5)
        self.roi_start.pack(side=tk.LEFT)
        tk.Label(button_frame, text="ROI End:").pack(side=tk.LEFT)
        self.roi_end = tk.Entry(button_frame, width=5)
        self.roi_end.pack(side=tk.LEFT)
        
        # ROI Set button
        roi_button = tk.Button(button_frame, text="Set ROI", command=self.set_roi)
        roi_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Reset Autoscale button
        reset_button = tk.Button(button_frame, text="Reset Autoscale", command=self.reset_autoscale)
        reset_button.pack(side=tk.LEFT, padx=5, pady=5)
        # data mode button

        self.data_mode_button = tk.Button(button_frame, text="{}".format(self.data_mode), command=self.toggle_data_mode)
        self.data_mode_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Image Autoscale Button
        self.image_autoscale_enabled = True  # Default to enabled
        self.image_autoscale_button = tk.Button(button_frame, text="Image Autoscale: ON", command=self.toggle_image_autoscale)
        self.image_autoscale_button.pack(side=tk.LEFT, padx=5, pady=5)

        tk.Label(button_frame, text="Y Center:").pack(side=tk.LEFT)
        self.y_center_entry = tk.Entry(button_frame, width=5)
        self.y_center_entry.pack(side=tk.LEFT)
        tk.Label(button_frame, text="Y Width:").pack(side=tk.LEFT)
        self.y_width_entry = tk.Entry(button_frame, width=5)
        self.y_width_entry.pack(side=tk.LEFT)


        apply_roi_button = tk.Button(button_frame, text="Apply Y ROI", command=self.apply_y_roi)
        apply_roi_button.pack(side=tk.LEFT, padx=5, pady=5)

    def apply_y_roi(self):
        """ Set Y ROI from center and width, update spectrum view. """
        try:
            center = int(self.y_center_entry.get())
            width = int(self.y_width_entry.get())

            half_width = int(round(width // 2))
            y_start = center - half_width
            y_end = center + half_width

            # Clamp to valid range
            y_start = max(0, y_start)
            y_end = min(self.data.shape[0], y_end)

            if y_end > y_start:
                self.spectrum_roi = (y_start, y_end)
                print(f"Updated Spectrum ROI: {self.spectrum_roi}")
                if self.data_mode == "Spectrum":
                    spectrum = self.frame_to_spectrum()
                    self.update_plot(spectrum)
            else:
                print("Invalid ROI: width too small or center out of bounds")

        except ValueError:
            print("Invalid input for ROI center or width")



    def toggle_image_autoscale(self):
        """ Enable or disable autoscaling for the image colormap """
        self.image_autoscale_enabled = not self.image_autoscale_enabled
        self.image_autoscale_button.config(text="Image Autoscale: ON" if self.image_autoscale_enabled else "Image Autoscale: OFF")
        
        if self.data_mode == "Image":
            self.update_image(self.data)  # Refresh image with the new setting

    def toggle_autoscale(self):
        self.autoscale_enabled = not self.autoscale_enabled

    def toggle_update(self):
        self.updating = not self.updating
        if self.updating:
            # change button colour to green
            self.update_button.config(bg='green')
        else:
            # change button colour to red
            self.update_button.config(bg='red')

    def set_roi(self):
        try:
            min_x = int(self.roi_start.get())
            max_x = int(self.roi_end.get())
            self.roi = (min_x, max_x)
        except ValueError:
            print("Invalid ROI values")

    def reset_autoscale(self):
        self.roi = None
        self.ax.relim()
        self.ax.autoscale_view()

    def update_plot(self, data):
        """ Updates the spectrum plot and ensures it redraws correctly. """
        self.ax.clear()  # Ensure old plot is removed
        dataX = data[:, 0]
        dataY = data[:, 1]

        self.ax.plot(dataX, dataY, 'r-')  # Replot with new data
        # draw a marker line at the 50th pixel's wavelength
        target_wl = dataX[50]

        # Option A: use axvline (spans full y‑axis automatically)
        self.ax.axvline(
            target_wl,
            color='blue',
            linestyle='-',
            linewidth=1
        )
        # Autoscale handling
        if self.autoscale_enabled:
            if self.roi:  # Use ROI for Y-scaling
                min_x, max_x = self.roi

                roi_data = dataY[min_x:max_x]
                if roi_data.size > 0:
                    self.plot_limits = np.min(roi_data), np.max(roi_data)
                    self.ax.set_ylim(*self.plot_limits)
        else:
            self.ax.set_ylim(*self.plot_limits)

        self.ax.set_xlim(dataX[0], dataX[-1])  # Set X limits to full range of data

        self.canvas.draw()  # Force Matplotlib to redraw

    def update_image(self, data):
        """ Update the displayed image while keeping zoom settings. """
        self.ax.clear()

        # Set colormap limits based on ROI autoscaling
        vmin, vmax = self.image_limits

        if self.image_autoscale_enabled and self.roi:
            min_x, max_x = self.roi
            min_x = max(0, min_x)
            max_x = min(data.shape[1], max_x)
            roi_data = data[:, min_x:max_x]

            if roi_data.size > 0:
                vmin, vmax = np.min(roi_data), np.max(roi_data)
                self.image_limits = (vmin, vmax)

        # Plot image
        self.ax.imshow(data, cmap='plasma', vmin=vmin, vmax=vmax)

        # Restore zoom limits if they exist
        if self.zoom_limits:
            self.ax.set_xlim(self.zoom_limits[0])
            self.ax.set_ylim(self.zoom_limits[1])

        self.canvas.draw()


    def frame_to_spectrum(self):
        """Return an (N×2) array [[x0,y0],…] or None on error."""
        arr = getattr(self, "data", None)
        if arr is None:
            return None

        # collapse any 3D → 2D
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        if arr.ndim != 2:
            print(f"frame_to_spectrum: expected 2D, got {arr.ndim}D")
            return None

        # clip ROI
        y0, y1 = self.spectrum_roi
        y0 = max(0, min(arr.shape[0], y0))
        y1 = max(0, min(arr.shape[0], y1))
        if y1 <= y0:
            y1 = y0 + 1

        # compute mean spectrum
        spec = arr[y0:y1, :].mean(axis=0)

        # choose x‐axis
        if len(self.wavelength_axis) == spec.size:
            x = self.wavelength_axis
        else:
            x = np.arange(spec.size)

        return np.column_stack((x, spec))
    # def monitor_image_file_old(self):

    #     while True:
    #         if self.updating:
    #             try:
    #                 if os.path.exists(self.image_file_path):
    #                     # Load data from the file
    #                     try:
    #                         self.data = np.load(self.image_file_path)
    #                         if len(self.data.shape) == 3:
    #                             self.data = self.data[:, :, 0]
    #                     except Exception as e:
    #                         print(f"Error loading data from file {self.image_file_path}: {e}")
    #                         time.sleep(1)
    #                         continue

    #                     if self.data_mode == "Image":
    #                         self.update_image(self.data)
    #                     else:
    #                         spectrum = self.frame_to_spectrum()
    #                         self.update_plot(spectrum)
    #             except PermissionError:
    #                 print(f"Permission denied to access file {self.image_file_path}.")
    #             except Exception as e:
    #                 print(f"Error processing file:\n{traceback.format_exc()}")
    #         time.sleep(0.1)  # Wait before checking again
    def monitor_image_file(self):
        """Worker thread: load .npy then schedule GUI update."""
        while True:
            if self.updating and os.path.exists(self.image_file_path):
                try:
                    arr = np.load(self.image_file_path)
                    if arr.ndim == 3:
                        arr = arr[:, :, 0]
                    self.data = arr
                    if self.data_mode == "Image":
                        self.root.after(0, self._safe_update_image, arr)
                    else:
                        spec = self.frame_to_spectrum()
                        if spec is not None:
                            self.root.after(0, self._safe_update_spectrum, spec)
                except PermissionError:
                    pass
                except Exception:
                    print("monitor_image_file:", traceback.format_exc())
            time.sleep(0.1)

    def monitor_wavelength_file(self):
        """Worker thread: load wavelengths then schedule spectrum update."""
        while True:
            if self.updating and os.path.exists(self.wavelengths_file_path):
                try:
                    wl = np.load(self.wavelengths_file_path)
                    self.wavelength_axis = wl
                    if self.data_mode == "Spectrum":
                        spec = self.frame_to_spectrum()
                        if spec is not None:
                            self.root.after(0, self._safe_update_spectrum, spec)
                except PermissionError:
                    pass
                except Exception:
                    print("monitor_wavelength_file:", traceback.format_exc())
            time.sleep(0.1)

    # def monitor_wavelength_file_old(self):
    #     while True:
    #         if self.updating:
    #             try:
    #                 if os.path.exists(self.wavelengths_file_path):
    #                     # Load data from the file
    #                     try:
    #                         self.wavelength_axis = np.load(self.wavelengths_file_path)
    #                     except Exception as e:
    #                         print(f"Error loading wavelengths from file {self.wavelengths_file_path}: {e}")
    #                         time.sleep(1)
    #                         continue

    #                     if self.data_mode == "Spectrum":
    #                         spectrum = self.frame_to_spectrum()
    #                         self.update_plot(spectrum)
    #             except PermissionError:
    #                 print(f"Permission denied to access file {self.wavelengths_file_path}.")
    #             except Exception as e:
    #                 print(f"Error processing file:\n{traceback.format_exc()}")
    #         time.sleep(0.1)  # Wait before checking again


    def start(self):
        # Start the Tkinter event loop
        self.root.mainloop()

# Run the GUI
if __name__ == "__main__":
    # Replace with your actual file path
    image_name = 'transient_data.npy'
    wavelengths = 'transient_wavelengths.npy'
    scriptDir = os.path.dirname(__file__)
    dataDir = os.path.join(scriptDir, "data", "transient_data")
    # files = sorted([x for x in os.listdir(dataDir) if x.endswith(".npz")])
    # file_path = os.path.join(dataDir, files[-1])

    plotter = LiveDataPlotter(image_name, wavelengths, dataDir, bin_centre=83, bin_width=30)
    plotter.start()


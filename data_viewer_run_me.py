import numpy as np
import matplotlib.pyplot as plt
import os
import time
import threading
import tkinter as tk
import traceback
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import RectangleSelector


class LiveDataPlotter:
    def __init__(self, file_path, **kwargs):
        self.file_path = file_path
        self.autoscale_enabled = True
        self.updating = True
        self.roi = None  # Region of Interest for autoscaling




        self.data_mode = "Image"
        self.spectrum_roi = (50,1100)

        self.image_limits = (None, None)

        self.bin_height = 30


        # Initialize Tkinter and Matplotlib
        self.root = tk.Tk()
        self.root.title("Live Data Plotter")

        # Create a Matplotlib figure embedded in Tkinter
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot([], [], 'r-')  # Initialize an empty plot
        self.ax.vlines([50], 0, 70000)
        
        self.cursor_label = tk.Label(self.root, text="X: --, Y: --, Intensity: --")
        self.cursor_label.pack(side=tk.BOTTOM)
        self.fig.canvas.mpl_connect("motion_notify_event", self.update_cursor)

        self.fig.canvas.mpl_connect("scroll_event", self.zoom)
        self.zoom_limits = None  # Store zoom range
        # Set up a Tkinter canvas for Matplotlib
        self._build_canvas()

        # Create control buttons and entry fields
        self.create_controls()

        # Start a background thread to monitor the file and update the plot
        self.monitor_thread = threading.Thread(target=self.monitor_file, daemon=True)
        self.monitor_thread.start()

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
        """ Rebuild the Matplotlib canvas and reinitialize the ROI selector. """
        if hasattr(self, "canvas"):  # Destroy old canvas if it exists
            self.canvas.get_tk_widget().destroy()

        self.fig, self.ax = plt.subplots()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)


    def toggle_data_mode(self):
        """ Toggle between 1D spectrum and 2D image display """
        self.data_mode = "Spectrum" if self.data_mode == "Image" else "Image"

        self._build_canvas()  # Rebuild the entire Matplotlib canvas

        if self.data_mode == "Spectrum":
            spectrum = self.frame_to_spectrum()
            self.ax.plot(np.arange(len(spectrum)), spectrum, 'r-')  # Plot 1D spectrum
        else:
            self.ax.imshow(self.data, cmap='plasma')  # Plot 2D image
        
        self.ax.set_title(self.data_mode)
        self.canvas.draw()

        # Update button text
        self.data_mode_button.config(text=self.data_mode)

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

        tk.Label(button_frame, text="Y Start:").pack(side=tk.LEFT)
        self.y_start_entry = tk.Entry(button_frame, width=5)
        self.y_start_entry.pack(side=tk.LEFT)
        tk.Label(button_frame, text="Y Finish:").pack(side=tk.LEFT)
        self.y_finish_entry = tk.Entry(button_frame, width=5)
        self.y_finish_entry.pack(side=tk.LEFT)

        apply_roi_button = tk.Button(button_frame, text="Apply Y ROI", command=self.apply_y_roi)
        apply_roi_button.pack(side=tk.LEFT, padx=5, pady=5)

    def apply_y_roi(self):
        """ Manually set Y ROI from textboxes and update spectrum view. """
        try:
            y_start = int(self.y_start_entry.get())
            y_finish = int(self.y_finish_entry.get())

            if 0 <= y_start < self.data.shape[0] and 0 <= y_finish < self.data.shape[0]:
                self.spectrum_roi = (min(y_start, y_finish), max(y_start, y_finish))
                print(f"Updated Spectrum ROI: {self.spectrum_roi}")

                # Update spectrum immediately
                if self.data_mode == "Spectrum":
                    spectrum = self.frame_to_spectrum()
                    self.update_plot(spectrum)
            else:
                print("Invalid Y values")
        except ValueError:
            print("Invalid input for Y ROI")


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
        x_values = np.arange(len(data))

        self.ax.plot(x_values, data, 'r-')  # Replot with new data
        self.ax.vlines([50], 0, 70000)

        # Autoscale handling
        if self.autoscale_enabled:
            if self.roi:  # Use ROI for Y-scaling
                min_x, max_x = self.roi
                roi_data = data[min_x:max_x]
                if roi_data.size > 0:
                    self.plot_limits = np.min(roi_data), np.max(roi_data)
                    self.ax.set_ylim(*self.plot_limits)
        else:
            self.ax.set_ylim(*self.plot_limits)



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
        """ Calculate spectrum by averaging the selected ROI in the image. """
        if self.spectrum_roi is None:
            roi = (0, self.data.shape[0])  # Default: use full range
        else:
            roi = self.spectrum_roi  # Use selected region

        center_y = self.data.shape[0] // 2
        bin_region = (max(0, center_y - self.bin_height), min(self.data.shape[0], center_y + self.bin_height))

        # print(bin_region)
        data_array = self.data[bin_region[0]:bin_region[1], :]

        # print(data_array.shape)

        spectrum_data = np.mean(data_array, axis=0)  # Average over the selected region

        # print(new_array.shape)
        print(spectrum_data.shape)

        # spectrum_data = np.mean(self.data[roi[0]:roi[1], bin_region[0]:bin_region[1]], axis=0)  
        # print(self.data.shape)
        # print(self.data)
        # print(spectrum_data.shape)
        return spectrum_data

    def monitor_file(self):
        while True:
            if self.updating:
                try:
                    if os.path.exists(self.file_path):
                        # Load data from the file
                        try:
                            self.data = np.load(self.file_path)
                            if len(self.data.shape) == 3:
                                self.data = self.data[:, :, 0]
                        except Exception as e:
                            print(f"Error loading data from file {self.file_path}: {e}")
                            time.sleep(1)
                            continue

                        if self.data_mode == "Image":
                            self.update_image(self.data)
                        else:
                            spectrum = self.frame_to_spectrum()
                            self.update_plot(spectrum)
                except PermissionError:
                    print(f"Permission denied to access file {self.file_path}.")
                except Exception as e:
                    print(f"Error processing file:\n{traceback.format_exc()}")
            time.sleep(0.1)  # Wait before checking again


    def start(self):
        # Start the Tkinter event loop
        self.root.mainloop()

# Run the GUI
if __name__ == "__main__":
    # Replace with your actual file path
    scriptDir = os.path.dirname(__file__)
    file_path = os.path.join(scriptDir, 'transient', 'transient_data.npy')

    plotter = LiveDataPlotter(file_path, bin_height=1)
    plotter.start()

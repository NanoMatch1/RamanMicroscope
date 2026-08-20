# data_viewer_run_me.py

import numpy as np
import matplotlib.pyplot as plt
import os
import time
import threading
import tkinter as tk
import traceback
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class LiveDataPlotter:
    def __init__(self, file_path, **kwargs):
        self.file_path = file_path
        self.autoscale_enabled       = True
        self.updating                = True
        self.roi                     = None
        self.zoom_limits             = None
        self.image_limits            = (None, None)
        self.plot_limits             = (0, 70000)

        self._y_center_default       = kwargs.get('bin_center', 50)
        self._y_width_default        = kwargs.get('bin_width',  10)

        self.data_mode               = "Spectrum"

        # ── CHANGED: spectrum_roi is now a Y-row range, not an X-pixel range ──
        # Previously this was used inconsistently — sometimes as X pixels,
        # sometimes as Y rows. It is now exclusively the Y-row range used by
        # frame_to_spectrum(). The X range is always the full sensor width.
        self.spectrum_roi            = (
            self._y_center_default - self._y_width_default // 2,
            self._y_center_default + self._y_width_default // 2,
        )
        # ── END CHANGE ────────────────────────────────────────────────────────

        self.bin_height              = kwargs.get("bin_height", 0)

        # Safe placeholder — shape matches PIXIS default ROI
        self.data                    = np.zeros((100, 1024), dtype=np.uint16)

        # ── CHANGED: flag used to pass new data from monitor thread to GUI ─────
        # The monitor thread writes to self._pending_data and sets this flag.
        # The GUI poll loop (running on the main thread via root.after) reads
        # the flag, grabs the data, and redraws. This avoids all direct
        # Tkinter/Matplotlib calls from the background thread.
        self._new_data_available     = False
        self._pending_data           = None
        self._data_lock              = threading.Lock()
        # ── END CHANGE ────────────────────────────────────────────────────────

        # ── Tkinter / Matplotlib setup ─────────────────────────────────────────
        self.root = tk.Tk()
        self.root.title("Live Data Plotter")

        self.cursor_label = tk.Label(
            self.root, text="X: --, Y: --, Intensity: --"
        )
        self.cursor_label.pack(side=tk.BOTTOM)

        self._build_canvas()
        self.create_controls()

        # Background file monitor thread
        self.monitor_thread = threading.Thread(
            target=self.monitor_file, daemon=True
        )
        self.monitor_thread.start()

        # ── CHANGED: start the GUI poll loop on the main thread ───────────────
        # _poll_for_new_data() reschedules itself every 100 ms via root.after,
        # keeping all Matplotlib/Tkinter calls on the main thread.
        self.root.after(100, self._poll_for_new_data)
        # ── END CHANGE ────────────────────────────────────────────────────────

        self.apply_y_roi()

    # --------------------------------------------------------------------------
    # GUI poll loop  ← NEW
    # --------------------------------------------------------------------------

    def _poll_for_new_data(self):
        """
        Called on the main thread every 100 ms via root.after().
        Checks whether the monitor thread has deposited a new frame,
        and if so redraws the plot.

        This is the correct Tkinter pattern for updating a GUI from a
        background thread — the thread never touches the GUI directly.
        """
        if self._new_data_available:
            with self._data_lock:
                frame = self._pending_data
                self._new_data_available = False

            if frame is not None:
                self.data = frame
                if self.data_mode == "Image":
                    self.update_image(self.data)
                else:
                    self.update_plot(self.frame_to_spectrum())

        # Reschedule on the main thread
        self.root.after(100, self._poll_for_new_data)

    # --------------------------------------------------------------------------
    # Zoom and cursor
    # --------------------------------------------------------------------------

    def zoom(self, event):
        """Zoom in/out using the mouse scroll wheel (image mode only)."""
        if event.inaxes is None or self.data_mode != "Image":
            return

        scale_factor = 1.2 if event.step > 0 else 0.8
        xlim         = self.ax.get_xlim()
        ylim         = self.ax.get_ylim()
        x_center     = (xlim[0] + xlim[1]) / 2
        y_center     = (ylim[0] + ylim[1]) / 2

        new_xlim = [x_center + (x - x_center) * scale_factor for x in xlim]
        new_ylim = [y_center + (y - y_center) * scale_factor for y in ylim]

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self.zoom_limits = (new_xlim, new_ylim)
        self.canvas.draw()

    def update_cursor(self, event):
        """Track mouse movement and update the cursor label (image mode only)."""
        if event.inaxes is None or self.data_mode != "Image":
            return
        x, y = int(event.xdata), int(event.ydata)
        if 0 <= x < self.data.shape[1] and 0 <= y < self.data.shape[0]:
            intensity = self.data[y, x]
            self.cursor_label.config(
                text=f"X: {x}, Y: {y}, Intensity: {intensity}"
            )

    # --------------------------------------------------------------------------
    # Canvas
    # --------------------------------------------------------------------------

    def _build_canvas(self):
        """Rebuild the Matplotlib canvas."""
        if hasattr(self, "canvas"):
            self.canvas.get_tk_widget().destroy()

        self.fig, self.ax = plt.subplots()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

        self.fig.canvas.mpl_connect("motion_notify_event", self.update_cursor)
        self.fig.canvas.mpl_connect("scroll_event", self.zoom)

    # --------------------------------------------------------------------------
    # Data mode toggle
    # --------------------------------------------------------------------------

    def toggle_data_mode(self):
        """Toggle between 1D spectrum and 2D image display."""
        self.data_mode = "Spectrum" if self.data_mode == "Image" else "Image"
        self._build_canvas()

        if self.data_mode == "Spectrum":
            self.update_plot(self.frame_to_spectrum())
        else:
            self.update_image(self.data)

        self.data_mode_button.config(text=self.data_mode)

    # --------------------------------------------------------------------------
    # Controls
    # --------------------------------------------------------------------------

    def create_controls(self):
        button_frame = tk.Frame(self.root)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(
            button_frame, text="Toggle Autoscale",
            command=self.toggle_autoscale
        ).pack(side=tk.LEFT, padx=5, pady=5)

        self.update_button = tk.Button(
            button_frame, text="Start/Stop Update",
            command=self.toggle_update
        )
        self.update_button.pack(side=tk.LEFT, padx=5, pady=5)

        tk.Label(button_frame, text="ROI Start:").pack(side=tk.LEFT)
        self.roi_start = tk.Entry(button_frame, width=5)
        self.roi_start.pack(side=tk.LEFT)

        tk.Label(button_frame, text="ROI End:").pack(side=tk.LEFT)
        self.roi_end = tk.Entry(button_frame, width=5)
        self.roi_end.pack(side=tk.LEFT)

        tk.Button(
            button_frame, text="Set ROI",
            command=self.set_roi
        ).pack(side=tk.LEFT, padx=5, pady=5)

        tk.Button(
            button_frame, text="Reset Autoscale",
            command=self.reset_autoscale
        ).pack(side=tk.LEFT, padx=5, pady=5)

        self.data_mode_button = tk.Button(
            button_frame, text=self.data_mode,
            command=self.toggle_data_mode
        )
        self.data_mode_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.image_autoscale_enabled = True
        self.image_autoscale_button  = tk.Button(
            button_frame, text="Image Autoscale: ON",
            command=self.toggle_image_autoscale
        )
        self.image_autoscale_button.pack(side=tk.LEFT, padx=5, pady=5)

        tk.Label(button_frame, text="Y Center:").pack(side=tk.LEFT)
        self.y_center_entry = tk.Entry(button_frame, width=5)
        self.y_center_entry.insert(0, str(self._y_center_default))
        self.y_center_entry.pack(side=tk.LEFT)

        tk.Label(button_frame, text="Y Width:").pack(side=tk.LEFT)
        self.y_width_entry = tk.Entry(button_frame, width=5)
        self.y_width_entry.insert(0, str(self._y_width_default))
        self.y_width_entry.pack(side=tk.LEFT)

        tk.Button(
            button_frame, text="Apply Y ROI",
            command=self.apply_y_roi
        ).pack(side=tk.LEFT, padx=5, pady=5)

        self.sensor_label = tk.Label(
            button_frame, text="Frame: -- × --", fg="grey"
        )
        self.sensor_label.pack(side=tk.LEFT, padx=10)

        # ── CHANGED: added update rate label ──────────────────────────────────
        # Shows how frequently the file is being reloaded, so you can confirm
        # the viewer is actually receiving new frames.
        self.rate_label = tk.Label(
            button_frame, text="Rate: -- fps", fg="grey"
        )
        self.rate_label.pack(side=tk.LEFT, padx=10)
        self._last_update_time = time.time()
        # ── END CHANGE ────────────────────────────────────────────────────────

    # --------------------------------------------------------------------------
    # Y ROI
    # --------------------------------------------------------------------------

    def apply_y_roi(self):
        """Set Y ROI from center and width entries, then refresh the plot."""
        try:
            center = int(self.y_center_entry.get())
            width  = int(self.y_width_entry.get())
        except (ValueError, AttributeError):
            center = self._y_center_default
            width  = self._y_width_default

        half_width = width // 2
        y_start    = max(0, center - half_width)
        y_end      = min(self.data.shape[0], center + half_width)

        if y_end > y_start:
            self.spectrum_roi = (y_start, y_end)
            print(f"Updated Spectrum ROI: {self.spectrum_roi}")
            if self.data_mode == "Spectrum":
                self.update_plot(self.frame_to_spectrum())
        else:
            print("Invalid ROI: width too small or center out of bounds.")

    # --------------------------------------------------------------------------
    # Autoscale / update toggles
    # --------------------------------------------------------------------------

    def toggle_image_autoscale(self):
        self.image_autoscale_enabled = not self.image_autoscale_enabled
        label = "ON" if self.image_autoscale_enabled else "OFF"
        self.image_autoscale_button.config(text=f"Image Autoscale: {label}")
        if self.data_mode == "Image":
            self.update_image(self.data)

    def toggle_autoscale(self):
        self.autoscale_enabled = not self.autoscale_enabled

    def toggle_update(self):
        self.updating = not self.updating
        self.update_button.config(bg='green' if self.updating else 'red')

    def set_roi(self):
        try:
            self.roi = (int(self.roi_start.get()), int(self.roi_end.get()))
        except ValueError:
            print("Invalid ROI values.")

    def reset_autoscale(self):
        self.roi = None
        self.ax.relim()
        self.ax.autoscale_view()

    # --------------------------------------------------------------------------
    # Plot update  (main thread only)
    # --------------------------------------------------------------------------

    def update_plot(self, data):
        """Update the spectrum plot. Must be called from the main thread."""
        self.ax.clear()
        self.ax.plot(np.arange(len(data)), data, 'r-')
        self.ax.vlines([50], 0, 70000, colors='blue', linestyles='dashed',
                       alpha=0.5)
        self.ax.set_xlabel("Pixel")
        self.ax.set_ylabel("Intensity (counts)")
        self.ax.set_title(
            f"Spectrum  |  Y rows {self.spectrum_roi[0]}–{self.spectrum_roi[1]}"
        )

        if self.autoscale_enabled and self.roi:
            min_x, max_x = self.roi
            roi_data = data[min_x:max_x]
            if roi_data.size > 0:
                self.plot_limits = (float(np.min(roi_data)),
                                    float(np.max(roi_data)))
        self.ax.set_ylim(*self.plot_limits)

        self._update_rate_label()
        self.sensor_label.config(
            text=f"Frame: {self.data.shape[1]} × {self.data.shape[0]}",
            fg="black"
        )
        self.canvas.draw()

    def update_image(self, data):
        """Update the image plot. Must be called from the main thread."""
        self.ax.clear()

        vmin, vmax = self.image_limits
        if self.image_autoscale_enabled and self.roi:
            min_x = max(0, self.roi[0])
            max_x = min(data.shape[1], self.roi[1])
            roi_data = data[:, min_x:max_x]
            if roi_data.size > 0:
                vmin, vmax = float(np.min(roi_data)), float(np.max(roi_data))
                self.image_limits = (vmin, vmax)

        self.ax.imshow(data, cmap='plasma', vmin=vmin, vmax=vmax,
                       aspect='auto')
        self.ax.set_title("Image")

        if self.zoom_limits:
            self.ax.set_xlim(self.zoom_limits[0])
            self.ax.set_ylim(self.zoom_limits[1])

        self._update_rate_label()
        self.sensor_label.config(
            text=f"Frame: {data.shape[1]} × {data.shape[0]}",
            fg="black"
        )
        self.canvas.draw()

    def _update_rate_label(self):
        """Update the fps label based on time since last redraw."""
        now      = time.time()
        elapsed  = now - self._last_update_time
        if elapsed > 0:
            fps = 1.0 / elapsed
            self.rate_label.config(
                text=f"Rate: {fps:.1f} fps", fg="black"
            )
        self._last_update_time = now

    # --------------------------------------------------------------------------
    # Spectrum extraction
    # --------------------------------------------------------------------------

    def frame_to_spectrum(self):
        """Average the selected Y-row ROI to produce a 1D spectrum."""
        if self.spectrum_roi is None:
            y_start, y_end = 0, self.data.shape[0]
        else:
            y_start = max(0, min(self.data.shape[0], self.spectrum_roi[0]))
            y_end   = max(0, min(self.data.shape[0], self.spectrum_roi[1]))

        if y_end <= y_start:
            y_end = y_start + 1

        return np.mean(self.data[y_start:y_end, :], axis=0)

    # --------------------------------------------------------------------------
    # File monitor  (background thread — never touches GUI)
    # --------------------------------------------------------------------------

    def monitor_file(self):
        """
        Background thread: reload the .npy file whenever it changes.

        This method NEVER calls any Tkinter or Matplotlib function directly.
        Instead it deposits the new frame into self._pending_data and sets
        self._new_data_available = True. The main-thread poll loop
        (_poll_for_new_data) picks it up and redraws safely.
        """
        last_mtime = None

        while True:
            if self.updating:
                try:
                    if os.path.exists(self.file_path):

                        # ── CHANGED: only reload when the file has changed ─────
                        # Previously the file was reloaded every 100 ms
                        # regardless of whether it had been updated, causing
                        # redundant redraws and masking the static-frame bug.
                        # Now we check the file modification time first.
                        mtime = os.path.getmtime(self.file_path)
                        if mtime == last_mtime:
                            time.sleep(0.05)
                            continue
                        last_mtime = mtime
                        # ── END CHANGE ────────────────────────────────────────

                        try:
                            raw = np.load(self.file_path)
                            if raw.ndim == 3:
                                raw = raw[:, :, 0]
                            if raw.ndim != 2:
                                print(
                                    f"Unexpected array shape {raw.shape} "
                                    f"— skipping."
                                )
                                time.sleep(0.1)
                                continue
                        except Exception as e:
                            print(f"Error loading {self.file_path}: {e}")
                            time.sleep(1)
                            continue

                        # Deposit frame for the main thread to pick up
                        with self._data_lock:
                            self._pending_data       = raw
                            self._new_data_available = True

                except PermissionError:
                    print(f"Permission denied: {self.file_path}")
                except Exception:
                    print(f"monitor_file error:\n{traceback.format_exc()}")

            time.sleep(0.05)

    # --------------------------------------------------------------------------
    # Entry point
    # --------------------------------------------------------------------------

    def start(self):
        self.root.mainloop()


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    script_dir = os.path.dirname(__file__)
    file_path  = os.path.join(
        script_dir, 'data', 'transient_data', 'transient_data.npy'
    )
    plotter = LiveDataPlotter(file_path, bin_center=50, bin_width=10)
    plotter.start()

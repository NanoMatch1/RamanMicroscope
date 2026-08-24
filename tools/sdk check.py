import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.patches as patches
from matplotlib.widgets import RectangleSelector
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import tkinter as tk
from pylablib.devices import PrincetonInstruments
from scipy.optimize import curve_fit
from scipy.special  import voigt_profile
import serial
import csv
import os




# 1. Initialize PICAM environment and list connected cameras
print("Searching for connected PIXIS cameras...")
cameras = PrincetonInstruments.list_cameras()
print(f"Found cameras: {cameras}")

if not cameras:
    raise RuntimeError("No Princeton Instruments cameras detected.")

# 2. Connect to the camera
camera_id = cameras[0]
cam = PrincetonInstruments.PicamCamera('2712050005')
print(f"Successfully connected to camera: {camera_id}")

# ── ROI helper — defined at top level so all options can access it ─────────
def apply_roi(x_bin, y_bin):
    """
    Read the current ROI from the camera, rebuild it with new binning
    values, and write it back.
    """
    current_rois = cam.get_attribute_value("ROIs")
    roi          = current_rois[0]

    try:
        new_roi = roi._replace(x_binning=x_bin, y_binning=y_bin)
    except AttributeError:
        new_roi = (0, 1024, x_bin, 0, 1024, y_bin)

    cam.set_attribute_value("ROIs", [new_roi])

        # ── Line profile models ────────────────────────────────────────────────

def gaussian(x, amplitude, center, sigma, offset):
            """
            Gaussian profile with background offset.
            f(x) = offset + amplitude * exp(-0.5 * ((x - center) / sigma)^2)
            """
            return offset + amplitude * np.exp(
                -0.5 * ((x - center) / sigma) ** 2
            )

def lorentzian(x, amplitude, center, gamma, offset):
            """
            Lorentzian (Cauchy) profile with background offset.
            f(x) = offset + amplitude * (gamma^2 / ((x - center)^2 + gamma^2))
            """
            return offset + amplitude * (
                gamma ** 2 / ((x - center) ** 2 + gamma ** 2)
            )

def voigt(x, amplitude, center, sigma, gamma, offset):
            """
            Voigt profile with background offset.
            Uses scipy.special.voigt_profile which computes the normalised
            Voigt. We scale by amplitude / voigt_profile(0, sigma, gamma)
            so that amplitude represents the true peak height.
            """
            peak_norm = voigt_profile(0, sigma, gamma)
            if peak_norm == 0:
                return np.full_like(x, offset, dtype=np.float64)
            return offset + (amplitude / peak_norm) * voigt_profile(
                x - center, sigma, gamma
            )

def r_squared(y_data, y_fit):
            """Compute R² coefficient of determination."""
            ss_res = np.sum((y_data - y_fit) ** 2)
            ss_tot = np.sum((y_data - y_data.mean()) ** 2)
            return 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0


print(f"Successfully connected to camera: {camera_id}")

def fit_profile(model_name, px, intensity):
    """
    Fit a named profile model to (px, intensity) data.
    Returns a dict of results or None on failure.

    Parameters
    ----------
    model_name : str
        One of 'Gaussian', 'Lorentzian', 'Voigt'.
    px : np.ndarray
        Pixel positions.
    intensity : np.ndarray
        Intensity values.

    Returns
    -------
    dict or None
    """
    if len(px) < 5:
        return None

    offset_guess    = float(np.percentile(intensity, 10))
    amplitude_guess = float(intensity.max() - offset_guess)
    center_guess    = float(px[np.argmax(intensity)])
    width_guess     = float((px[-1] - px[0]) / 6)

    try:
        if model_name == "Gaussian":
            p0     = [amplitude_guess, center_guess, width_guess, offset_guess]
            lower  = [0, float(px[0]),  1e-6, 0      ]
            upper  = [np.inf, float(px[-1]), np.inf, np.inf]
            popt, pcov = curve_fit(
                gaussian, px, intensity,
                p0=p0, bounds=(lower, upper), maxfev=10000
            )
            amplitude, center, sigma, offset = popt
            perr        = np.sqrt(np.diag(pcov))
            center_err  = perr[1]
            y_fit       = gaussian(px, *popt)
            fwhm        = 2.355 * abs(sigma)

        elif model_name == "Lorentzian":
            p0     = [amplitude_guess, center_guess, width_guess, offset_guess]
            lower  = [0, float(px[0]),  1e-6, 0      ]
            upper  = [np.inf, float(px[-1]), np.inf, np.inf]
            popt, pcov = curve_fit(
                lorentzian, px, intensity,
                p0=p0, bounds=(lower, upper), maxfev=10000
            )
            amplitude, center, gamma, offset = popt
            perr        = np.sqrt(np.diag(pcov))
            center_err  = perr[1]
            y_fit       = lorentzian(px, *popt)
            fwhm        = 2.0 * abs(gamma)

        elif model_name == "Voigt":
            p0     = [amplitude_guess, center_guess,
                    width_guess, width_guess, offset_guess]
            lower  = [0, float(px[0]),  1e-6, 1e-6, 0      ]
            upper  = [np.inf, float(px[-1]), np.inf, np.inf, np.inf]
            popt, pcov = curve_fit(
                voigt, px, intensity,
                p0=p0, bounds=(lower, upper), maxfev=10000
            )
            amplitude, center, sigma, gamma, offset = popt
            perr        = np.sqrt(np.diag(pcov))
            center_err  = perr[1]
            y_fit       = voigt(px, *popt)
            # Approximate Voigt FWHM (Thompson et al. 1987)
            fg   = 2.355 * sigma
            fl   = 2.0   * gamma
            fwhm = 0.5346 * fl + np.sqrt(
                0.2166 * fl ** 2 + fg ** 2
            )

        else:
            return None

        return {
            "model"      : model_name,
            "center"     : center,
            "center_err" : center_err,
            "amplitude"  : amplitude,
            "fwhm"       : fwhm,
            "r_squared"  : r_squared(intensity, y_fit),
            "y_fit"      : y_fit,
            "popt"       : popt,
        }

    except RuntimeError:
        print(f"  {model_name} fit did not converge.")
        return None
    except Exception as e:
        print(f"  {model_name} fit error: {e}")
        return None



try:
    # 3. Ask the user what they want to do
    print("\nWhat would you like to do?")
    print("  [1] Take a snapshot")
    print("  [2] Temperature options")
    print("  [3] Acquisition parameters")
    print("  [4] Live acquisition")
    print("  [5] Laser calibration")
    choice = input("Enter 1, 2, 3, 4, or 5: ").strip()

    # --- Option 1: Snapshot ---
    if choice == "1":
        try:
            new_exp = float(input("  Enter new exposure time (ms): ").strip())
            cam.set_attribute_value("Exposure Time", new_exp)
        except ValueError:
            print("  Invalid input — please enter a numeric value.")

        print(f"  Exposure time set to: {cam.get_attribute_value('Exposure Time')} ms")

        try:
            new_frames = int(input("  Enter number of averaging frames: ").strip())
            if new_frames < 1:
                print("  Must be at least 1. Defaulting to 1.")
                new_frames = 1
        except ValueError:
            print("  Invalid input — defaulting to 1 frame.")
            new_frames = 1

        cam.set_attribute_value("Readout Count", new_frames)
        print(f"  Averaging frames set to: {new_frames}")

        detector_shape = cam.get_detector_size()
        print(f"  Sensor Resolution: {detector_shape[0]} x {detector_shape[1]}")

        print(f"  Acquiring and averaging {new_frames} frame(s)...")
        cam.start_acquisition()

        accumulated = None
        frames_collected = 0

        try:
            for i in range(new_frames):
                cam.wait_for_frame(timeout=10)
                frame = cam.read_newest_image()

                if frame is not None:
                    if accumulated is None:
                        accumulated = frame.astype(np.float64)
                    else:
                        accumulated += frame.astype(np.float64)
                    frames_collected += 1
                    print(f"  Collected frame {frames_collected}/{new_frames}")
                else:
                    print(f"  Warning: frame {i+1} was empty, skipping.")

        except Exception as e:
            print(f"  Frame acquisition failed: {e}")

        cam.stop_acquisition()

        if frames_collected > 0:
            image_data = accumulated / frames_collected
            print(f"  Averaged {frames_collected} frame(s).")
            print(f"  Final image shape : {image_data.shape}")
            print(f"  Intensity range   : {image_data.min():.1f} – {image_data.max():.1f} counts")

            plt.figure(figsize=(6, 6))
            plt.imshow(image_data, cmap='gray')
            plt.title(f"PIXIS 1024 — {frames_collected} frame average | {new_exp:.1f} ms")
            plt.colorbar(label='Intensity (Counts)')
            plt.show()
        else:
            print("  Error: No frames collected.")

    # --- Option 2: Temperature Options ---
    elif choice == "2":
        print("\nTemperature options:")
        print("  [1] Check current sensor temperature")
        print("  [2] Set target temperature")
        temp_choice = input("Enter 1 or 2: ").strip()

        if temp_choice == "1":
            temp      = cam.get_attribute_value("Sensor Temperature Reading")
            setpoint  = cam.get_attribute_value("Sensor Temperature Set Point")
            status    = cam.get_attribute_value("Sensor Temperature Status")
            print(f"  Current temperature : {temp:.2f} °C")
            print(f"  Target setpoint     : {setpoint:.2f} °C")
            print(f"  Lock status         : {status}")

        elif temp_choice == "2":
            current_temp     = cam.get_attribute_value("Sensor Temperature Reading")
            current_setpoint = cam.get_attribute_value("Sensor Temperature Set Point")
            current_status   = cam.get_attribute_value("Sensor Temperature Status")
            print(f"  Current temperature : {current_temp:.2f} °C")
            print(f"  Current setpoint    : {current_setpoint:.2f} °C")
            print(f"  Lock status         : {current_status}")

            try:
                new_setpoint = float(input("\n  Enter desired target temperature (°C): ").strip())
            except ValueError:
                raise ValueError("Invalid input — please enter a numeric temperature value.")

            cam.set_attribute_value("Sensor Temperature Set Point", new_setpoint)
            print(f"  Target temperature set to: {new_setpoint:.2f} °C")

            print("\n  Would you like to monitor the temperature?")
            print("    [1] Continuously monitor temperature and lock status")
            print("    [2] Exit")
            monitor_choice = input("  Enter 1 or 2: ").strip()

            if monitor_choice == "1":
                print("\n  Monitoring temperature (Ctrl+C to stop)...\n")
                try:
                    while True:
                        current_temp = cam.get_attribute_value("Sensor Temperature Reading")
                        status       = cam.get_attribute_value("Sensor Temperature Status")
                        print(f"  Temperature: {current_temp:.2f} °C  |  Setpoint: {new_setpoint:.2f} °C  |  Status: {status}")
                        if status == "Locked":
                            print("\n  Temperature locked at target.")
                            break
                        time.sleep(5)
                except KeyboardInterrupt:
                    print("\n  Monitoring stopped by user.")

            elif monitor_choice == "2":
                print("  Exiting without monitoring.")

            else:
                print("  Invalid choice.")

        else:
            print("  Invalid choice. Please enter 1 or 2.")

    # --- Option 3: Acquisition Parameters ---
    elif choice == "3":
        print("\nAcquisition parameters:")
        print("  [1] View current parameters")
        print("  [2] Set parameters")
        acq_choice = input("Enter 1 or 2: ").strip()

        if acq_choice == "1":
            exp_time      = cam.get_attribute_value("Exposure Time")
            adc_speed     = cam.get_attribute_value("ADC Speed")
            adc_gain      = cam.get_attribute_value("ADC Analog Gain")
            readout_count = cam.get_attribute_value("Readout Count")
            clean_trigger = cam.get_attribute_value("Clean Until Trigger")
            print(f"  Exposure time       : {exp_time:.1f} ms")
            print(f"  ADC speed           : {adc_speed} MHz")
            print(f"  ADC analogue gain   : {adc_gain}")
            print(f"  Readout count       : {readout_count}")
            print(f"  Clean until trigger : {clean_trigger}")

        elif acq_choice == "2":
            exp_time      = cam.get_attribute_value("Exposure Time")
            adc_speed     = cam.get_attribute_value("ADC Speed")
            adc_gain      = cam.get_attribute_value("ADC Analog Gain")
            readout_count = cam.get_attribute_value("Readout Count")
            clean_trigger = cam.get_attribute_value("Clean Until Trigger")
            print(f"\n  Current parameters:")
            print(f"    Exposure time       : {exp_time:.1f} ms")
            print(f"    ADC speed           : {adc_speed} MHz")
            print(f"    ADC analogue gain   : {adc_gain}")
            print(f"    Readout count       : {readout_count}")
            print(f"    Clean until trigger : {clean_trigger}")

            print("\n  Which parameter would you like to change?")
            print("    [1] Exposure time")
            print("    [2] Number of averaging frames")
            print("    [3] ADC speed")
            print("    [4] ADC analogue gain")
            print("    [5] Clean until trigger")
            param_choice = input("  Enter 1–5: ").strip()

            if param_choice == "1":
                try:
                    new_exp = float(input("  Enter new exposure time (ms): ").strip())
                    cam.set_attribute_value("Exposure Time", new_exp)
                    print(f"  Exposure time set to: {new_exp:.1f} ms")
                except ValueError:
                    print("  Invalid input — please enter a numeric value.")

            elif param_choice == "2":
                try:
                    new_frames = int(input("  Enter number of averaging frames: ").strip())
                    if new_frames < 1:
                        print("  Must be at least 1.")
                    else:
                        cam.set_attribute_value("Readout Count", new_frames)
                        print(f"  Averaging frames set to: {new_frames}")
                except ValueError:
                    print("  Invalid input — please enter a whole number.")

            elif param_choice == "3":
                print("  Available ADC speeds (MHz): 0.1, 1.0, 2.0")
                try:
                    new_speed = float(input("  Enter ADC speed (MHz): ").strip())
                    cam.set_attribute_value("ADC Speed", new_speed)
                    print(f"  ADC speed set to: {new_speed} MHz")
                except ValueError:
                    print("  Invalid input — please enter a numeric value.")

            elif param_choice == "4":
                print("  Available gain settings: Low, Medium, High")
                new_gain = input("  Enter gain setting: ").strip()
                if new_gain not in ["Low", "Medium", "High"]:
                    print("  Invalid gain — must be Low, Medium, or High.")
                else:
                    cam.set_attribute_value("ADC Analog Gain", new_gain)
                    print(f"  ADC analogue gain set to: {new_gain}")

            elif param_choice == "5":
                print("  Enable clean until trigger? (True/False)")
                new_clean = input("  Enter True or False: ").strip()
                if new_clean not in ["True", "False"]:
                    print("  Invalid input — must be True or False.")
                else:
                    cam.set_attribute_value("Clean Until Trigger", new_clean == "True")
                    print(f"  Clean until trigger set to: {new_clean}")

            else:
                print("  Invalid choice.")

        else:
            print("  Invalid choice. Please enter 1 or 2.")

    # --- Option 4: Live Acquisition ---
    elif choice == "4":

        # Ask for initial exposure time via console before opening the GUI
        try:
            live_exp = float(input("  Enter initial exposure time (ms): ").strip())
            cam.set_attribute_value("Exposure Time", live_exp)
        except ValueError:
            print("  Invalid input — defaulting to 100 ms.")
            live_exp = 100.0
            cam.set_attribute_value("Exposure Time", live_exp)

        cam.set_attribute_value("Readout Count", 1)

        # ── Optional TRIAX connection ──────────────────────────────────────────
        connect_triax = input("  Connect to TRIAX spectrometer? (y/n): ").strip().lower()
        triax_live = None

        if connect_triax == 'y':
            triax_live_port = input("  Enter TRIAX COM port (e.g. COM16): ").strip()
            try:
                triax_live = serial.Serial(
                    port     = triax_live_port,
                    baudrate = 4800,
                    bytesize = serial.EIGHTBITS,
                    parity   = serial.PARITY_NONE,
                    stopbits = serial.STOPBITS_ONE,
                    timeout  = 2
                )
                time.sleep(0.5)
                print(f"  Connected to TRIAX on {triax_live_port}.")

                # Initialise
                triax_live.write(bytes([248]))
                time.sleep(0.5)
                triax_live.reset_input_buffer()
                triax_live.write(b'H0\r')
                time.sleep(0.5)
                response = triax_live.read(triax_live.in_waiting)
                decoded  = response.decode('ascii', errors='replace')
                has_digits = any(c.isdigit() for c in decoded)
                if 'o' in decoded and has_digits:
                    print("  TRIAX already initialised.")
                else:
                    print("  TRIAX not initialised — initialising...")
                    triax_live.write(b' ')
                    last_data_time = time.time()
                    while True:
                        if triax_live.in_waiting > 0:
                            triax_live.read(triax_live.in_waiting)
                            last_data_time = time.time()
                        if time.time() - last_data_time > 5:
                            break
                        time.sleep(0.1)
                    triax_live.write(bytes([248]))
                    time.sleep(0.5)
                    print("  TRIAX initialisation complete.")

            except serial.SerialException as e:
                print(f"  Failed to connect to TRIAX: {e}")
                triax_live = None

        # ── TRIAX helpers ──────────────────────────────────────────────────────
        def triax_live_send(command_bytes, wait=0.5):
            triax_live.reset_input_buffer()
            triax_live.reset_output_buffer()
            triax_live.write(command_bytes)
            time.sleep(wait)
            response = triax_live.read(triax_live.in_waiting)
            return response.decode('ascii', errors='replace')

        def triax_live_get_position():
            response = triax_live_send(b'H0\r')
            try:
                return int(response.strip()[1:])
            except ValueError:
                return None

        def triax_live_move_to_wavelength(wavelength_nm):
            """
            Move the TRIAX to the target wavelength using the reference point:
            101310 steps = 765.00 nm.
            Returns the new position in steps or None on failure.
            """
            REFERENCE_STEPS      = 101310
            REFERENCE_WAVELENGTH = 765.00
            STEPS_PER_NM         = 101310 / 765.00

            delta_wavelength = wavelength_nm - REFERENCE_WAVELENGTH
            delta_steps      = int(round(delta_wavelength * STEPS_PER_NM))
            target_steps     = REFERENCE_STEPS + delta_steps

            current_steps = triax_live_get_position()
            if current_steps is None:
                return None

            relative_move = target_steps - current_steps

            print(f"  TRIAX move to {wavelength_nm:.3f} nm  |  "
                  f"target: {target_steps} steps  |  "
                  f"current: {current_steps} steps  |  "
                  f"relative: {relative_move:+d} steps")

            if relative_move == 0:
                print("  Already at target wavelength.")
                return current_steps

            command = f'F0,{relative_move}\r'.encode('ascii')
            response = triax_live_send(command, wait=1.0)
            print(f"  TRIAX response: {response.strip()}")

            # Poll until settled
            poll_start = time.time()
            while time.time() - poll_start < 30:
                new_pos = triax_live_get_position()
                if new_pos is not None:
                    print(f"  Position poll: {new_pos} steps")
                    if abs(new_pos - target_steps) < 5:
                        print(f"  TRIAX at target: {new_pos} steps")
                        return new_pos
                time.sleep(0.5)

            print("  TRIAX move timeout.")
            return None

        # ── Build the tkinter GUI window ───────────────────────────────────────
        root = tk.Tk()
        root.title("PIXIS 1024 — Live Acquisition")
        root.resizable(False, False)

        # ── Main layout ────────────────────────────────────────────────────────
        left_frame  = tk.Frame(root)
        right_frame = tk.Frame(root)
        left_frame.grid(row=0, column=0, padx=(10, 5), pady=10)
        right_frame.grid(row=0, column=1, padx=(5, 10), pady=10)

        fig_live, ax_live = plt.subplots(figsize=(5, 5), dpi=80)
        fig_live.tight_layout()
        canvas_live = FigureCanvasTkAgg(fig_live, master=left_frame)
        canvas_live.get_tk_widget().pack()

        fig_spec, (ax_x, ax_y) = plt.subplots(2, 1, figsize=(4, 5))
        fig_spec.suptitle("Region Spectra", fontsize=10)
        fig_spec.tight_layout(rect=[0, 0, 1, 0.95])
        canvas_spec = FigureCanvasTkAgg(fig_spec, master=right_frame)
        canvas_spec.get_tk_widget().pack()

        # ── Control panel ──────────────────────────────────────────────────────
        control_frame = tk.Frame(root, relief=tk.GROOVE, borderwidth=2)
        control_frame.grid(row=1, column=0, columnspan=2, padx=10,
                           pady=(0, 10), sticky="ew")

        # ── Row 0: Live controls label ─────────────────────────────────────────
        tk.Label(
            control_frame, text="Live controls",
            font=("TkDefaultFont", 9, "bold")
        ).grid(row=0, column=0, columnspan=12, sticky="w", padx=8, pady=(6, 2))

        # ── Row 1: Exposure | X bin | Y bin | Avg frames | Acquire | Status ───
        tk.Label(control_frame, text="Exposure time (ms):").grid(
            row=1, column=0, padx=(8, 2), pady=4, sticky="e"
        )
        exp_var   = tk.StringVar(value=str(live_exp))
        exp_entry = tk.Entry(control_frame, textvariable=exp_var, width=7)
        exp_entry.grid(row=1, column=1, padx=2, pady=4)

        tk.Label(control_frame, text="X binning:").grid(
            row=1, column=2, padx=(12, 2), pady=4, sticky="e"
        )
        xbin_var   = tk.StringVar(value="1")
        xbin_entry = tk.Entry(control_frame, textvariable=xbin_var, width=4)
        xbin_entry.grid(row=1, column=3, padx=2, pady=4)

        tk.Label(control_frame, text="Y binning:").grid(
            row=1, column=4, padx=(12, 2), pady=4, sticky="e"
        )
        ybin_var   = tk.StringVar(value="1")
        ybin_entry = tk.Entry(control_frame, textvariable=ybin_var, width=4)
        ybin_entry.grid(row=1, column=5, padx=2, pady=4)

        tk.Label(control_frame, text="Avg frames:").grid(
            row=1, column=6, padx=(12, 2), pady=4, sticky="e"
        )
        avg_var   = tk.StringVar(value="1")
        avg_entry = tk.Entry(control_frame, textvariable=avg_var, width=4)
        avg_entry.grid(row=1, column=7, padx=2, pady=4)

        apply_exp_button = tk.Button(control_frame, text="Apply Live Settings")
        apply_exp_button.grid(row=1, column=8, padx=(12, 4), pady=4)

        acquire_button = tk.Button(
            control_frame, text="Acquire",
            bg="#d0eaff", activebackground="#a0c8f0"
        )
        acquire_button.grid(row=1, column=9, padx=(4, 8), pady=4)

        status_label = tk.Label(
            control_frame,
            text=f"Live  |  {live_exp:.1f} ms  |  ~{1000/live_exp:.2f} Hz  |  bin 1×1  |  1 frame",
            fg="green", anchor="w"
        )
        status_label.grid(row=2, column=0, columnspan=10,
                          padx=8, pady=(0, 4), sticky="w")

        # ── Row 3: TRIAX wavelength control ───────────────────────────────────
        tk.Label(
            control_frame, text="Spectrometer",
            font=("TkDefaultFont", 9, "bold")
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))

        if triax_live is not None:
            current_pos = triax_live_get_position()
            triax_status_text = f"Connected  |  position: {current_pos} steps"
            triax_status_colour = "green"
        else:
            triax_status_text   = "Not connected"
            triax_status_colour = "grey"

        tk.Label(control_frame, text="Target wavelength (nm):").grid(
            row=3, column=2, padx=(12, 2), pady=4, sticky="e"
        )
        wl_var   = tk.StringVar(value="765.000")
        wl_entry = tk.Entry(
            control_frame, textvariable=wl_var, width=8,
            state=tk.NORMAL if triax_live is not None else tk.DISABLED
        )
        wl_entry.grid(row=3, column=3, padx=2, pady=4)

        move_wl_button = tk.Button(
            control_frame, text="Move to wavelength",
            bg="#d4f0d4", activebackground="#a8e0a8",
            state=tk.NORMAL if triax_live is not None else tk.DISABLED
        )
        move_wl_button.grid(row=3, column=4, padx=(8, 4), pady=4)

        triax_status_label = tk.Label(
            control_frame, text=triax_status_text,
            fg=triax_status_colour, anchor="w"
        )
        triax_status_label.grid(row=3, column=5, columnspan=5,
                                 padx=8, pady=4, sticky="w")

        # ── Row 4: Region selection ────────────────────────────────────────────
        tk.Label(
            control_frame, text="Region selection",
            font=("TkDefaultFont", 9, "bold")
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))

        selector_status = tk.Label(control_frame, text="No region selected", fg="grey")
        selector_status.grid(row=4, column=2, columnspan=5,
                              padx=5, pady=(6, 2), sticky="w")

        apply_sel_button = tk.Button(
            control_frame, text="Apply Selection", state=tk.DISABLED
        )
        apply_sel_button.grid(row=4, column=7, padx=4, pady=(6, 2))

        clear_sel_button = tk.Button(
            control_frame, text="Clear Selection", state=tk.DISABLED
        )
        clear_sel_button.grid(row=4, column=8, padx=4, pady=(6, 2))

        # ── Shared state ───────────────────────────────────────────────────────
        state = {
            "interval_ms"  : int(live_exp),
            "ani"          : None,
            "paused"       : False,
            "acquiring"    : False,
            "last_frame"   : None,
            "selection"    : None,
            "rect_patch"   : None,
        }

        # ── Move to wavelength callback ────────────────────────────────────────
        def on_move_to_wavelength():
            if triax_live is None:
                return
            try:
                target_wl = float(wl_var.get().strip())
            except ValueError:
                triax_status_label.config(
                    text="Invalid wavelength — enter a number.", fg="red"
                )
                return

            # Pause live acquisition during move
            state["paused"] = True
            triax_status_label.config(
                text=f"Moving to {target_wl:.3f} nm...", fg="orange"
            )
            root.update()

            cam.stop_acquisition() if hasattr(cam, 'stop_acquisition') else None

            new_pos = triax_live_move_to_wavelength(target_wl)

            if new_pos is not None:
                triax_status_label.config(
                    text=f"At {target_wl:.3f} nm  |  position: {new_pos} steps",
                    fg="green"
                )
            else:
                triax_status_label.config(
                    text=f"Move to {target_wl:.3f} nm failed.", fg="red"
                )

            # Resume live acquisition
            cam.start_acquisition()
            state["paused"] = False

        move_wl_button.config(command=on_move_to_wavelength)

        # ── Apply live settings ────────────────────────────────────────────────
        def apply_live_settings():
            try:
                new_exp = float(exp_var.get().strip())
                if new_exp <= 0:
                    raise ValueError("Exposure must be positive.")
            except ValueError:
                status_label.config(
                    text="Invalid exposure time — enter a positive number.", fg="red"
                )
                return

            x_bin = parse_binning(xbin_var, "X")
            if x_bin is None:
                return
            y_bin = parse_binning(ybin_var, "Y")
            if y_bin is None:
                return

            state["paused"] = True
            status_label.config(text="Applying settings...", fg="orange")
            root.update()

            cam.stop_acquisition()
            cam.set_attribute_value("Exposure Time", new_exp)
            apply_roi(x_bin, y_bin)
            cam.set_attribute_value("Readout Count", 1)

            new_interval = int(new_exp)
            state["interval_ms"] = new_interval
            if state["ani"] is not None:
                state["ani"].event_source.interval = new_interval

            cam.start_acquisition()
            state["paused"] = False

            implied_rate = 1000 / new_exp
            status_label.config(
                text=(
                    f"Live  |  {new_exp:.1f} ms  |  ~{implied_rate:.2f} Hz  |"
                    f"  bin {x_bin}×{y_bin}  |  1 frame (live)"
                ),
                fg="green"
            )

        apply_exp_button.config(command=apply_live_settings)

        # ── Helper: parse binning ──────────────────────────────────────────────
        def parse_binning(var, label):
            try:
                val = int(var.get().strip())
                if val < 1:
                    raise ValueError
                return val
            except ValueError:
                status_label.config(
                    text=f"Invalid {label} binning — must be a positive integer.",
                    fg="red"
                )
                return None

        # ── Acquire button ─────────────────────────────────────────────────────
        def run_acquire():
            if state["acquiring"]:
                return

            try:
                acq_exp = float(exp_var.get().strip())
                if acq_exp <= 0:
                    raise ValueError
            except ValueError:
                status_label.config(text="Invalid exposure time for acquire.", fg="red")
                return

            x_bin = parse_binning(xbin_var, "X")
            if x_bin is None:
                return
            y_bin = parse_binning(ybin_var, "Y")
            if y_bin is None:
                return

            try:
                n_frames = int(avg_var.get().strip())
                if n_frames < 1:
                    raise ValueError
            except ValueError:
                status_label.config(
                    text="Invalid frame count — must be a positive integer.", fg="red"
                )
                return

            state["paused"]    = True
            state["acquiring"] = True
            acquire_button.config(state=tk.DISABLED)
            apply_exp_button.config(state=tk.DISABLED)

            status_label.config(
                text=f"Acquiring {n_frames} frame(s) at {acq_exp:.1f} ms  |  bin {x_bin}×{y_bin}...",
                fg="orange"
            )
            root.update()

            time.sleep(max(0.5, (state["interval_ms"] / 1000) + 0.2))

            try:
                cam.stop_acquisition()
            except Exception:
                pass

            cam.set_attribute_value("Exposure Time", acq_exp)
            apply_roi(x_bin, y_bin)
            cam.set_attribute_value("Readout Count", n_frames)
            cam.start_acquisition()

            accumulated      = None
            frames_collected = 0

            try:
                for i in range(n_frames):
                    timeout = (acq_exp / 1000) + 5
                    cam.wait_for_frame(timeout=timeout)
                    frame = cam.read_newest_image()

                    if frame is not None:
                        if accumulated is None:
                            accumulated = frame.astype(np.float64)
                        else:
                            accumulated += frame.astype(np.float64)
                        frames_collected += 1
                        status_label.config(
                            text=f"  Collected frame {frames_collected}/{n_frames}...",
                            fg="orange"
                        )
                        root.update()
                    else:
                        print(f"  Warning: frame {i+1} was empty, skipping.")

            except Exception as e:
                print(f"  Acquire failed: {e}")
                status_label.config(text=f"Acquire failed: {e}", fg="red")

            try:
                cam.stop_acquisition()
            except Exception:
                pass

            if frames_collected > 0 and accumulated is not None:
                image_data = accumulated / frames_collected
                state["last_frame"] = image_data
                im.set_data(image_data)
                im.set_clim(vmin=image_data.min(), vmax=image_data.max())
                ax_live.set_title(
                    f"PIXIS 1024 — Acquired  |  {frames_collected}× avg  |"
                    f"  {acq_exp:.1f} ms  |  bin {x_bin}×{y_bin}"
                )
                canvas_live.draw()

            cam.set_attribute_value("Readout Count", 1)
            cam.set_attribute_value("Exposure Time", acq_exp)
            apply_roi(x_bin, y_bin)

            new_interval = int(acq_exp)
            state["interval_ms"] = new_interval
            if state["ani"] is not None:
                state["ani"].event_source.interval = new_interval

            cam.start_acquisition()

            state["acquiring"] = False
            state["paused"]    = False
            acquire_button.config(state=tk.NORMAL)
            apply_exp_button.config(state=tk.NORMAL)

            implied_rate = 1000 / acq_exp
            status_label.config(
                text=(
                    f"Live  |  {acq_exp:.1f} ms  |  ~{implied_rate:.2f} Hz  |"
                    f"  bin {x_bin}×{y_bin}  |  acquired {frames_collected} frame(s)"
                ),
                fg="green"
            )

        acquire_button.config(command=run_acquire)

        # ── Rectangle selector ─────────────────────────────────────────────────
        def on_select(eclick, erelease):
            x0 = int(min(eclick.xdata,   erelease.xdata))
            x1 = int(max(eclick.xdata,   erelease.xdata))
            y0 = int(min(eclick.ydata,   erelease.ydata))
            y1 = int(max(eclick.ydata,   erelease.ydata))

            if state["last_frame"] is not None:
                h, w = state["last_frame"].shape
                x0 = max(0, min(x0, w - 1))
                x1 = max(0, min(x1, w - 1))
                y0 = max(0, min(y0, h - 1))
                y1 = max(0, min(y1, h - 1))

            state["selection"] = (x0, x1, y0, y1)

            if state["rect_patch"] is not None:
                state["rect_patch"].remove()
            rect = patches.Rectangle(
                (x0, y0), x1 - x0, y1 - y0,
                linewidth=1.5, edgecolor='red', facecolor='none'
            )
            state["rect_patch"] = ax_live.add_patch(rect)
            canvas_live.draw()

            selector_status.config(
                text=f"Region: x[{x0}:{x1}]  y[{y0}:{y1}]", fg="black"
            )
            apply_sel_button.config(state=tk.NORMAL)
            clear_sel_button.config(state=tk.NORMAL)

        rect_selector = RectangleSelector(
            ax_live, on_select,
            useblit=True, button=[1],
            minspanx=5, minspany=5,
            spancoords='pixels',
            interactive=True
        )

        # ── Apply selection ────────────────────────────────────────────────────
        def apply_selection():
            if state["last_frame"] is None or state["selection"] is None:
                return

            x0, x1, y0, y1 = state["selection"]
            region = state["last_frame"][y0:y1, x0:x1].astype(np.float64)

            if region.size == 0:
                selector_status.config(text="Selection too small.", fg="red")
                return

            x_spectrum = region.mean(axis=0)
            x_pixels   = np.arange(x0, x0 + region.shape[1])
            y_spectrum = region.mean(axis=1)
            y_pixels   = np.arange(y0, y0 + region.shape[0])

            model_colours = {
                "Gaussian"   : "gold",
                "Lorentzian" : "lime",
                "Voigt"      : "magenta",
            }

            for axis_label, ax, base_colour, px, intensity, span_range in [
                ("X", ax_x, "steelblue", x_pixels, x_spectrum, (1,   1020)),
                ("Y", ax_y, "tomato",    y_pixels, y_spectrum, (550, 650 )),
            ]:
                ax.cla()
                full_px  = x_pixels if axis_label == "X" else y_pixels
                full_int = x_spectrum if axis_label == "X" else y_spectrum
                ax.plot(full_px, full_int, color=base_colour,
                        linewidth=1, label="Spectrum", alpha=0.7)
                ax.axvspan(*span_range, alpha=0.08, color=base_colour,
                           label="Fit region")
                ax.set_xlabel(f"{axis_label} pixel")
                ax.set_ylabel("Mean intensity")
                ax.grid(True, alpha=0.3)

                best_model = None
                best_r2    = -np.inf
                title_lines = [
                    f"{axis_label} spectrum  "
                    f"({'rows' if axis_label == 'X' else 'cols'} "
                    f"{y0}–{y1 if axis_label == 'X' else x0}–{x1})"
                ]

                fit_mask = (
                    (px >= span_range[0]) & (px <= span_range[1])
                )
                fit_px  = px[fit_mask]
                fit_int = intensity[fit_mask]

                for model_name, colour in model_colours.items():
                    result = fit_profile(model_name, fit_px, fit_int)
                    if result is None:
                        title_lines.append(f"{model_name}: failed")
                        continue

                    px_fine = np.linspace(fit_px[0], fit_px[-1], 500)
                    if model_name == "Gaussian":
                        y_fine = gaussian(px_fine, *result["popt"])
                    elif model_name == "Lorentzian":
                        y_fine = lorentzian(px_fine, *result["popt"])
                    else:
                        y_fine = voigt(px_fine, *result["popt"])

                    ax.plot(px_fine, y_fine, color=colour, linewidth=1.5,
                            linestyle='--', label=f"{model_name} fit")

                    title_lines.append(
                        f"{model_name}: centre {result['center']:.2f}"
                        f" ± {result['center_err']:.2f} px  "
                        f"FWHM {result['fwhm']:.2f} px  "
                        f"R²={result['r_squared']:.4f}"
                    )

                    if result["r_squared"] > best_r2:
                        best_r2    = result["r_squared"]
                        best_model = model_name

                if best_model is not None:
                    title_lines.append(f"Best fit: {best_model}  (R²={best_r2:.4f})")

                ax.set_title("\n".join(title_lines), fontsize=7)
                ax.legend(fontsize=7)

            fig_spec.tight_layout(rect=[0, 0, 1, 0.95])
            canvas_spec.draw()
            selector_status.config(
                text="Fits complete — see plot titles and console for results.",
                fg="black"
            )

        apply_sel_button.config(command=apply_selection)

        # ── Clear selection ────────────────────────────────────────────────────
        def clear_selection():
            state["selection"] = None
            if state["rect_patch"] is not None:
                state["rect_patch"].remove()
                state["rect_patch"] = None
            canvas_live.draw()
            ax_x.cla()
            ax_x.set_title("X spectrum")
            ax_y.cla()
            ax_y.set_title("Y spectrum")
            canvas_spec.draw()
            selector_status.config(text="No region selected", fg="grey")
            apply_sel_button.config(state=tk.DISABLED)
            clear_sel_button.config(state=tk.DISABLED)

        clear_sel_button.config(command=clear_selection)

        # ── Acquire first frame ────────────────────────────────────────────────
        cam.start_acquisition()
        cam.wait_for_frame(timeout=10)
        first_frame = cam.read_newest_image()
        state["last_frame"] = first_frame

        im = ax_live.imshow(first_frame, cmap='gray', animated=True)
        cbar = fig_live.colorbar(im, ax=ax_live, label='Intensity (Counts)')
        ax_live.set_title(f"PIXIS 1024 — Live | {live_exp:.1f} ms")

        ref_line = ax_live.axvline(
            x=50, color='cyan', linewidth=1, linestyle='--', alpha=0.8
        )

        ax_x.set_title("X spectrum")
        ax_x.set_xlabel("X pixel")
        ax_x.set_ylabel("Mean intensity")
        ax_y.set_title("Y spectrum")
        ax_y.set_xlabel("Y pixel")
        ax_y.set_ylabel("Mean intensity")

        # ── Frame update loop ──────────────────────────────────────────────────
        def update_frame(frame_number):
            if state["paused"]:
                return [im, ref_line]

            try:
                cam.wait_for_frame(timeout=5)
                new_frame = cam.read_newest_image()
                if new_frame is not None:
                    state["last_frame"] = new_frame
                    # Downcast to float32 to halve memory usage during rendering
                    im.set_data(new_frame.astype(np.float32))
                    im.set_clim(vmin=new_frame.min(), vmax=new_frame.max())
            except Exception as e:
                print(f"  Frame update failed: {e}")

            return [im, ref_line]

            try:
                cam.wait_for_frame(timeout=5)
                new_frame = cam.read_newest_image()
                if new_frame is not None:
                    state["last_frame"] = new_frame
                    im.set_data(new_frame)
                    im.set_clim(vmin=new_frame.min(), vmax=new_frame.max())
            except Exception as e:
                print(f"  Frame update failed: {e}")

            return [im, ref_line]

        state["ani"] = animation.FuncAnimation(
            fig_live,
            update_frame,
            interval=state["interval_ms"],
            blit=True,
            cache_frame_data=False
        )

        # ── Clean shutdown ─────────────────────────────────────────────────────
        def on_close():
            state["ani"].event_source.stop()
            cam.stop_acquisition()
            if triax_live is not None:
                triax_live.close()
                print("  TRIAX connection closed.")
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

        print("  Live acquisition stopped.")
    elif choice == "4":

        try:
            live_exp = float(input("  Enter initial exposure time (ms): ").strip())
            cam.set_attribute_value("Exposure Time", live_exp)
        except ValueError:
            print("  Invalid input — defaulting to 100 ms.")
            live_exp = 100.0
            cam.set_attribute_value("Exposure Time", live_exp)

        cam.set_attribute_value("Readout Count", 1)

        # --- Build the tkinter GUI window ---
        root = tk.Tk()
        root.title("PIXIS 1024 — Live Acquisition")
        root.resizable(False, False)

        # ── Main layout: image canvas left, spectra canvas right ──────────────
        left_frame  = tk.Frame(root)
        right_frame = tk.Frame(root)
        left_frame.grid(row=0, column=0, padx=(10, 5), pady=10)
        right_frame.grid(row=0, column=1, padx=(5, 10), pady=10)

        fig_live, ax_live = plt.subplots(figsize=(5, 5))
        fig_live.tight_layout()
        canvas_live = FigureCanvasTkAgg(fig_live, master=left_frame)
        canvas_live.get_tk_widget().pack()

        fig_spec, (ax_x, ax_y) = plt.subplots(2, 1, figsize=(4, 5))
        fig_spec.suptitle("Region Spectra", fontsize=10)
        fig_spec.tight_layout(rect=[0, 0, 1, 0.95])
        canvas_spec = FigureCanvasTkAgg(fig_spec, master=right_frame)
        canvas_spec.get_tk_widget().pack()

        # ── Control panel ──────────────────────────────────────────────────────
        control_frame = tk.Frame(root, relief=tk.GROOVE, borderwidth=2)
        control_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")

        # ── Row 0: Live controls label ─────────────────────────────────────────
        tk.Label(
            control_frame, text="Live controls", font=("TkDefaultFont", 9, "bold")
        ).grid(row=0, column=0, columnspan=9, sticky="w", padx=8, pady=(6, 2))

        # ── Row 1: Exposure | X bin | Y bin | Avg frames | Acquire | Status ───
        tk.Label(control_frame, text="Exposure time (ms):").grid(
            row=1, column=0, padx=(8, 2), pady=4, sticky="e"
        )
        exp_var   = tk.StringVar(value=str(live_exp))
        exp_entry = tk.Entry(control_frame, textvariable=exp_var, width=7)
        exp_entry.grid(row=1, column=1, padx=2, pady=4)

        tk.Label(control_frame, text="X binning:").grid(
            row=1, column=2, padx=(12, 2), pady=4, sticky="e"
        )
        xbin_var   = tk.StringVar(value="1")
        xbin_entry = tk.Entry(control_frame, textvariable=xbin_var, width=4)
        xbin_entry.grid(row=1, column=3, padx=2, pady=4)

        tk.Label(control_frame, text="Y binning:").grid(
            row=1, column=4, padx=(12, 2), pady=4, sticky="e"
        )
        ybin_var   = tk.StringVar(value="1")
        ybin_entry = tk.Entry(control_frame, textvariable=ybin_var, width=4)
        ybin_entry.grid(row=1, column=5, padx=2, pady=4)

        tk.Label(control_frame, text="Avg frames:").grid(
            row=1, column=6, padx=(12, 2), pady=4, sticky="e"
        )
        avg_var   = tk.StringVar(value="1")
        avg_entry = tk.Entry(control_frame, textvariable=avg_var, width=4)
        avg_entry.grid(row=1, column=7, padx=2, pady=4)

        apply_exp_button = tk.Button(control_frame, text="Apply Live Settings")
        apply_exp_button.grid(row=1, column=8, padx=(12, 4), pady=4)

        acquire_button = tk.Button(
            control_frame, text="Acquire", bg="#d0eaff", activebackground="#a0c8f0"
        )
        acquire_button.grid(row=1, column=9, padx=(4, 8), pady=4)

        status_label = tk.Label(
            control_frame,
            text=f"Live  |  {live_exp:.1f} ms  |  ~{1000/live_exp:.2f} Hz  |  bin 1×1  |  1 frame",
            fg="green", anchor="w"
        )
        status_label.grid(row=2, column=0, columnspan=10, padx=8, pady=(0, 4), sticky="w")

        # ── Row 3: Selection controls ──────────────────────────────────────────
        tk.Label(
            control_frame, text="Region selection", font=("TkDefaultFont", 9, "bold")
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))

        selector_status = tk.Label(control_frame, text="No region selected", fg="grey")
        selector_status.grid(row=3, column=2, columnspan=5, padx=5, pady=(6, 2), sticky="w")

        apply_sel_button = tk.Button(
            control_frame, text="Apply Selection", state=tk.DISABLED
        )
        apply_sel_button.grid(row=3, column=7, padx=4, pady=(6, 2))

        clear_sel_button = tk.Button(
            control_frame, text="Clear Selection", state=tk.DISABLED
        )
        clear_sel_button.grid(row=3, column=8, padx=4, pady=(6, 2))

        # ── Shared state ───────────────────────────────────────────────────────
        state = {
            "last_popt"      : None,
            "triax_position" : 101310,    
            "interval_ms" : int(live_exp),
            "ani"         : None,
            "paused"      : False,
            "acquiring"   : False,   # True while a multi-frame acquire is running
            "last_frame"  : None,
            "selection"   : None,
            "rect_patch"  : None,
        }

        # ── Helper: parse and validate binning entry ───────────────────────────
        def parse_binning(var, label):
            """Return a positive integer from a StringVar, or None on error."""
            try:
                val = int(var.get().strip())
                if val < 1:
                    raise ValueError
                return val
            except ValueError:
                status_label.config(
                    text=f"Invalid {label} binning — must be a positive integer.",
                    fg="red"
                )
                return None

        # ── Apply live settings ────────────────────────────────────────────────
        def apply_live_settings():
            """Pause the loop, apply exposure and binning, then resume."""
            try:
                new_exp = float(exp_var.get().strip())
                if new_exp <= 0:
                    raise ValueError("Exposure must be positive.")
            except ValueError:
                status_label.config(
                    text="Invalid exposure time — enter a positive number.", fg="red"
                )
                return

            x_bin = parse_binning(xbin_var, "X")
            if x_bin is None:
                return
            y_bin = parse_binning(ybin_var, "Y")
            if y_bin is None:
                return

            state["paused"] = True
            status_label.config(text="Applying settings...", fg="orange")
            root.update()

            cam.stop_acquisition()
            cam.set_attribute_value("Exposure Time", new_exp)
            apply_roi(x_bin, y_bin)
            cam.set_attribute_value("Readout Count", 1)

            new_interval = int(new_exp)
            state["interval_ms"] = new_interval
            if state["ani"] is not None:
                state["ani"].event_source.interval = new_interval

            cam.start_acquisition()
            state["paused"] = False

            implied_rate = 1000 / new_exp
            status_label.config(
                text=(
                    f"Live  |  {new_exp:.1f} ms  |  ~{implied_rate:.2f} Hz  |"
                    f"  bin {x_bin}×{y_bin}  |  1 frame (live)"
                ),
                fg="green"
            )

        apply_exp_button.config(command=apply_live_settings)

        # ── Acquire: stop live, capture N averaged frames, resume live ─────────
        def acquire_frames():
            try:
                num_frames = int(avg_var.get().strip())
                if num_frames < 1:
                    raise ValueError("Must be at least 1 frame.")
            except ValueError:
                status_label.config(
                    text="Invalid number of frames — must be a positive integer.", fg="red"
                )
                return

            state["paused"] = True
            status_label.config(text=f"Acquiring {num_frames} frame(s)...", fg="orange")
            root.update()

            cam.stop_acquisition()
            cam.set_attribute_value("Readout Count", num_frames)
            cam.start_acquisition()

            accumulated = None
            frames_collected = 0

            try:
                for i in range(num_frames):
                    cam.wait_for_frame(timeout=10)
                    frame = cam.read_newest_image()

                    if frame is not None:
                        if accumulated is None:
                            accumulated = frame.astype(np.float64)
                        else:
                            accumulated += frame.astype(np.float64)
                        frames_collected += 1
                        status_label.config(
                            text=f"Acquired {frames_collected}/{num_frames} frame(s)...", fg="orange"
                        )
                        root.update()
                    else:
                        print(f"  Warning: frame {i+1} was empty, skipping.")

            except Exception as e:
                print(f"  Frame acquisition failed: {e}")

            cam.stop_acquisition()
            cam.set_attribute_value("Readout Count", 1)
            cam.start_acquisition()
            state["paused"] = False

            if frames_collected > 0:
                image_data = accumulated / frames_collected
                print(f"  Averaged {frames_collected} frame(s).")
                print(f"  Final image shape : {image_data.shape}")
                print(f"  Intensity range   : {image_data.min():.1f} – {image_data.max():.1f} counts")

                plt.figure(figsize=(6, 6))
                plt.imshow(image_data, cmap='gray')
                plt.title(f"PIXIS 1024 — {frames_collected} frame average | {live_exp:.1f} ms")
                plt.colorbar(label='Intensity (Counts)')
                plt.show()
            else:
                print("  Error: No frames collected.")

        # ── Rectangle selector ─────────────────────────────────────────────────
        def on_select(eclick, erelease):
            x0 = int(min(eclick.xdata,   erelease.xdata))
            x1 = int(max(eclick.xdata,   erelease.xdata))
            y0 = int(min(eclick.ydata,   erelease.ydata))
            y1 = int(max(eclick.ydata,   erelease.ydata))

            if state["last_frame"] is not None:
                h, w = state["last_frame"].shape
                x0 = max(0, min(x0, w - 1))
                x1 = max(0, min(x1, w - 1))
                y0 = max(0, min(y0, h - 1))
                y1 = max(0, min(y1, h - 1))

            state["selection"] = (x0, x1, y0, y1)

            if state["rect_patch"] is not None:
                state["rect_patch"].remove()
            rect = patches.Rectangle(
                (x0, y0), x1 - x0, y1 - y0,
                linewidth=1.5, edgecolor='red', facecolor='none'
            )
            state["rect_patch"] = ax_live.add_patch(rect)
            canvas_live.draw()

            selector_status.config(
                text=f"Region: x[{x0}:{x1}]  y[{y0}:{y1}]", fg="black"
            )
            apply_sel_button.config(state=tk.NORMAL)
            clear_sel_button.config(state=tk.NORMAL)

        rect_selector = RectangleSelector(
            ax_live, on_select,
            useblit=True, button=[1],
            minspanx=5, minspany=5,
            spancoords='pixels',
            interactive=True
        )



        # ── Apply selection — compute spectra and run all three fits ───────────
        def apply_selection():
            """
            Extract the selected region from the last captured frame, plot
            the averaged X and Y spectra, and run Gaussian, Lorentzian, and
            Voigt fits over the fixed fitting regions.
            """
            if state["last_frame"] is None or state["selection"] is None:
                return

            x0, x1, y0, y1 = state["selection"]
            region = state["last_frame"][y0:y1, x0:x1].astype(np.float64)

            if region.size == 0:
                selector_status.config(text="Selection too small.", fg="red")
                return

            # ── Compute spectra ────────────────────────────────────────────────
            x_spectrum = region.mean(axis=0)
            x_pixels   = np.arange(x0, x0 + region.shape[1])

            y_spectrum = region.mean(axis=1)
            y_pixels   = np.arange(y0, y0 + region.shape[0])

            # ── Mask to fitting windows ────────────────────────────────────────
            fit_x_mask = (x_pixels >= 1)   & (x_pixels <= 1020)
            fit_y_mask = (y_pixels >= 550) & (y_pixels <= 650)

            fit_x_px  = x_pixels[fit_x_mask]
            fit_x_int = x_spectrum[fit_x_mask]
            fit_y_px  = y_pixels[fit_y_mask]
            fit_y_int = y_spectrum[fit_y_mask]

            model_colours = {
                "Gaussian"   : "gold",
                "Lorentzian" : "lime",
                "Voigt"      : "magenta",
            }

            # ── Plot and fit both axes ─────────────────────────────────────────
            for axis_label, ax, base_colour, px, intensity, span_range in [
                ("X", ax_x, "steelblue", fit_x_px, fit_x_int, (1,    1020)),
                ("Y", ax_y, "tomato",    fit_y_px, fit_y_int, (550,  650 )),
            ]:
                ax.cla()

                # Plot the full spectrum behind the fit region
                full_px  = x_pixels if axis_label == "X" else y_pixels
                full_int = x_spectrum if axis_label == "X" else y_spectrum
                ax.plot(full_px, full_int, color=base_colour,
                        linewidth=1, label="Spectrum", alpha=0.7)
                ax.axvspan(*span_range, alpha=0.08, color=base_colour,
                           label="Fit region")

                ax.set_xlabel(f"{axis_label} pixel")
                ax.set_ylabel("Mean intensity")
                ax.grid(True, alpha=0.3)

                best_model  = None
                best_r2     = -np.inf
                title_lines = [
                    f"{axis_label} spectrum  "
                    f"({'rows' if axis_label == 'X' else 'cols'} "
                    f"{y0}–{y1 if axis_label == 'X' else x0}–{x1})"
                ]

                print(f"\n  ── {axis_label} spectrum fits ──────────────────")

                for model_name, colour in model_colours.items():
                    result = fit_profile(model_name, px, intensity)

                    if result is None:
                        title_lines.append(f"{model_name}: failed")
                        continue

                    # Overlay fitted curve over the fit window
                    px_fine  = np.linspace(px[0], px[-1], 500)
                    if model_name == "Gaussian":
                        y_fine = gaussian(px_fine, *result["popt"])
                    elif model_name == "Lorentzian":
                        y_fine = lorentzian(px_fine, *result["popt"])
                    else:
                        y_fine = voigt(px_fine, *result["popt"])

                    ax.plot(px_fine, y_fine, color=colour, linewidth=1.5,
                            linestyle='--', label=f"{model_name} fit")

                    title_lines.append(
                        f"{model_name}: centre {result['center']:.2f}"
                        f" ± {result['center_err']:.2f} px  "
                        f"FWHM {result['fwhm']:.2f} px  "
                        f"R²={result['r_squared']:.4f}"
                    )

                    print(
                        f"  {model_name}:\n"
                        f"    Centre    : {result['center']:.4f}"
                        f" ± {result['center_err']:.4f} px\n"
                        f"    FWHM      : {result['fwhm']:.4f} px\n"
                        f"    Amplitude : {result['amplitude']:.2f} counts\n"
                        f"    R²        : {result['r_squared']:.6f}"
                    )

                    if result["r_squared"] > best_r2:
                        best_r2    = result["r_squared"]
                        best_model = model_name

                if best_model is not None:
                    title_lines.append(f"Best fit: {best_model}  (R²={best_r2:.4f})")
                    print(f"  → Best fit: {best_model}  (R²={best_r2:.4f})")

                ax.set_title("\n".join(title_lines), fontsize=7)
                ax.legend(fontsize=7)

            fig_spec.tight_layout(rect=[0, 0, 1, 0.95])
            canvas_spec.draw()

            # ── Selector status summary ────────────────────────────────────────
            selector_status.config(
                text="Fits complete — see plot titles and console for results.",
                fg="black"
            )

        apply_sel_button.config(command=apply_selection)

        # ── Clear selection ────────────────────────────────────────────────────
        def clear_selection():
            state["selection"] = None
            if state["rect_patch"] is not None:
                state["rect_patch"].remove()
                state["rect_patch"] = None
            canvas_live.draw()

            ax_x.cla()
            ax_x.set_title("X spectrum")
            ax_y.cla()
            ax_y.set_title("Y spectrum")
            canvas_spec.draw()

            selector_status.config(text="No region selected", fg="grey")
            apply_sel_button.config(state=tk.DISABLED)
            clear_sel_button.config(state=tk.DISABLED)

        clear_sel_button.config(command=clear_selection)

        # ── Acquire first frame and initialise the live plot ───────────────────
        cam.start_acquisition()
        cam.wait_for_frame(timeout=10)
        first_frame = cam.read_newest_image()
        state["last_frame"] = first_frame

        first_frame = cam.read_newest_image()
        state["last_frame"] = first_frame

        im = ax_live.imshow(
            first_frame.astype(np.float32),
            cmap='gray', animated=True
        )
        cbar = fig_live.colorbar(im, ax=ax_live, label='Intensity (Counts)')
        ax_live.set_title(f"PIXIS 1024 — Live | {live_exp:.1f} ms")

        ax_x.set_title("X spectrum")
        ax_x.set_xlabel("X pixel")
        ax_x.set_ylabel("Mean intensity")
        ax_y.set_title("Y spectrum")
        ax_y.set_xlabel("Y pixel")
        ax_y.set_ylabel("Mean intensity")

        # ── Frame update loop ──────────────────────────────────────────────────
        im = ax_live.imshow(first_frame, cmap='gray', animated=True)
        ax_live.set_title(f"PIXIS 1024 — Live | {live_exp:.1f} ms")

        # Fixed reference line at x = 50
        ref_line = ax_live.axvline(x=50, color='cyan', linewidth=1,
                                   linestyle='--', alpha=0.8)

        def update_frame(frame_number):
            if state["paused"]:
                return [im, ref_line]

            try:
                cam.wait_for_frame(timeout=5)
                new_frame = cam.read_newest_image()
                if new_frame is not None:
                    state["last_frame"] = new_frame
                    im.set_data(new_frame)
                    im.set_clim(vmin=new_frame.min(), vmax=new_frame.max())
            except Exception as e:
                print(f"  Frame update failed: {e}")

            return [im, ref_line]



        state["ani"] = animation.FuncAnimation(
            fig_live,
            update_frame,
            interval=state["interval_ms"],
            blit=True,
            cache_frame_data=False
        )

        # ── Clean shutdown ─────────────────────────────────────────────────────
        def on_close():
            state["ani"].event_source.stop()
            cam.stop_acquisition()
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

        print("  Live acquisition stopped.")

    # --- Option 5: Wavelength Identification ---
    elif choice == "5":

        print("\n  Wavelength Identification")
        print("  ─────────────────────────────────────────────")
        print("  This will move the spectrometer to a known position,")
        print("  capture a frame, and fit the laser line to identify")
        print("  the current wavelength.\n")

        # ── TRIAX connection ───────────────────────────────────────────────────
        triax_port = input("  Enter COM port for TRIAX (e.g. COM16): ").strip()
        print(f"  Connecting to TRIAX on {triax_port}...")
        try:
            triax = serial.Serial(
                port     = triax_port,
                baudrate = 4800,
                bytesize = serial.EIGHTBITS,
                parity   = serial.PARITY_NONE,
                stopbits = serial.STOPBITS_ONE,
                timeout  = 2
            )
            time.sleep(0.5)
            print(f"  Connected to TRIAX on {triax_port}.")
        except serial.SerialException as e:
            print(f"  Failed to connect to TRIAX: {e}")
            triax = None

        if triax is None:
            print("  Wavelength identification aborted — no TRIAX connection.")

        else:
            # ── TRIAX helpers ──────────────────────────────────────────────────
            def triax_send(command_bytes, wait=0.5):
                triax.reset_input_buffer()
                triax.reset_output_buffer()
                triax.write(command_bytes)
                time.sleep(wait)
                response = triax.read(triax.in_waiting)
                return response.decode('ascii', errors='replace')

            def triax_get_position():
                response = triax_send(b'H0\r')
                try:
                    return int(response.strip()[1:])
                except ValueError:
                    print(f"  Could not parse TRIAX position: {response.strip()}")
                    return None

            def triax_move_relative(steps):
                command = f'F0,{steps}\r'.encode('ascii')
                print(f"  TRIAX sending    : F0,{steps}")
                response = triax_send(command, wait=1.0)
                print(f"  TRIAX response   : {response.strip()}")
                return response

            def triax_initialise():
                triax.write(bytes([248]))
                time.sleep(0.5)
                response = triax_send(b'H0\r')
                has_digits = any(c.isdigit() for c in response)
                if 'o' in response and has_digits:
                    print("  TRIAX already initialised.")
                else:
                    print("  TRIAX not initialised — initialising...")
                    triax.write(b' ')
                    last_data_time = time.time()
                    while True:
                        if triax.in_waiting > 0:
                            data = triax.read(triax.in_waiting)
                            print(f"  Init: {data.decode('ascii', errors='replace')!r}")
                            last_data_time = time.time()
                        if time.time() - last_data_time > 5:
                            print("  TRIAX initialisation complete.")
                            break
                        time.sleep(0.1)
                    triax.write(bytes([248]))
                    time.sleep(0.5)

                def triax_live_move_to_wavelength(wavelength_nm):
                    """
                    Move the TRIAX to the target wavelength using the polynomial
                    calibration from triax_calibrations.json.
                    steps = a*wl^2 + b*wl + c
                    """
                    # Polynomial coefficients from triax_calibrations.json
                    a, b, c = 0.010777978279028598, 92.69332901444886, 24091.71

                    target_steps  = int(round(a * wavelength_nm**2 + b * wavelength_nm + c))
                    current_steps = triax_live_get_position()

                    if current_steps is None:
                        return None

                    relative_move = target_steps - current_steps

                    print(f"  TRIAX move to {wavelength_nm:.3f} nm  |  "
                        f"target: {target_steps} steps  |  "
                        f"current: {current_steps} steps  |  "
                        f"relative: {relative_move:+d} steps")

                    if relative_move == 0:
                        print("  Already at target wavelength.")
                        return current_steps

                    command = f'F0,{relative_move}\r'.encode('ascii')
                    response = triax_live_send(command, wait=1.0)
                    print(f"  TRIAX response: {response.strip()}")

                    # Poll until settled
                    poll_start = time.time()
                    while time.time() - poll_start < 30:
                        new_pos = triax_live_get_position()
                        if new_pos is not None:
                            print(f"  Position poll: {new_pos} steps")
                            if abs(new_pos - target_steps) < 5:
                                print(f"  TRIAX at target: {new_pos} steps")
                                return new_pos
                        time.sleep(0.5)

                    print("  TRIAX move timeout.")
                    return None

            
            # ── Camera configuration ───────────────────────────────────────────
            try:
                wl_exp = float(input("  Enter exposure time (ms): ").strip())
            except ValueError:
                print("  Defaulting to 100 ms.")
                wl_exp = 100.0

            cam.set_attribute_value("Exposure Time", wl_exp)
            cam.set_attribute_value("Readout Count", 1)
            apply_roi(1, 1)

            # ── Acquire and fit helper ─────────────────────────────────────────
            def acquire_and_fit():
                """
                Acquire a single averaged frame, extract the ROI spectrum
                x[10:1024] y[550:650], and fit with Voigt only.
                Returns (center, center_err, fwhm, r2) or None if no peak found.
                """
                try:
                    cam.stop_acquisition()
                except Exception:
                    pass

                cam.start_acquisition()
                accumulated      = None
                frames_collected = 0

                try:
                    timeout = (wl_exp / 1000) + 5
                    cam.wait_for_frame(timeout=timeout)
                    frame = cam.read_newest_image()
                    if frame is not None:
                        accumulated      = frame.astype(np.float64)
                        frames_collected = 1
                except Exception as e:
                    print(f"  Frame acquisition error: {e}")

                try:
                    cam.stop_acquisition()
                except Exception:
                    pass

                if frames_collected == 0 or accumulated is None:
                    print("  Acquisition failed.")
                    return None, None

                full_frame = accumulated
                region     = full_frame[550:650, 10:1024]
                x_spectrum = region.mean(axis=0)
                x_pixels   = np.arange(10, 1024)

                # Check if there is a meaningful peak above background
                offset_guess    = float(np.percentile(x_spectrum, 10))
                amplitude_guess = float(x_spectrum.max() - offset_guess)

                if amplitude_guess < 50:
                    print(f"  No significant peak found "
                          f"(amplitude {amplitude_guess:.1f} counts — threshold 50 counts).")
                    return None, full_frame

                center_guess = float(x_pixels[np.argmax(x_spectrum)])
                half_max     = offset_guess + amplitude_guess / 2
                above_half   = x_pixels[x_spectrum > half_max]
                width_guess  = float(above_half[-1] - above_half[0]) if len(above_half) > 1 else 5.0
                width_guess  = max(1.0, min(width_guess, 50.0))

                print(f"  Peak found — amplitude: {amplitude_guess:.1f} counts  "
                      f"centre guess: {center_guess:.1f} px")

                try:
                    p0    = [amplitude_guess, center_guess, width_guess, width_guess, offset_guess]
                    lower = [0, float(x_pixels[0]),  1e-6, 1e-6, 0]
                    upper = [np.inf, float(x_pixels[-1]), np.inf, np.inf, np.inf]
                    popt, pcov = curve_fit(
                        voigt, x_pixels, x_spectrum,
                        p0=p0, bounds=(lower, upper), maxfev=50000
                    )
                    amplitude, center, sigma, gamma, offset = popt
                    perr       = np.sqrt(np.diag(pcov))
                    center_err = perr[1]
                    y_fit      = voigt(x_pixels, *popt)
                    fg         = 2.355 * sigma
                    fl         = 2.0 * gamma
                    fwhm       = 0.5346 * fl + np.sqrt(0.2166 * fl**2 + fg**2)
                    ss_res     = np.sum((x_spectrum - y_fit) ** 2)
                    ss_tot     = np.sum((x_spectrum - x_spectrum.mean()) ** 2)
                    r2         = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

                    print(f"  Voigt fit — centre: {center:.4f} ± {center_err:.4f} px  "
                          f"FWHM: {fwhm:.4f} px  R²: {r2:.6f}")

                    return (center, center_err, fwhm, r2), full_frame

                except Exception as e:
                    print(f"  Voigt fit failed: {e}")
                    return None, full_frame

            # ── Known reference positions ──────────────────────────────────────
            # Each entry: (triax_steps, known_wavelength_nm)
            SEARCH_POSITIONS = [
                (101310, 765.00),
                (105310, None),     # Higher wavelength — wavelength unknown
            ]

            # ── Initialise TRIAX ───────────────────────────────────────────────
            triax_initialise()
            print(f"  Current TRIAX position: {triax_get_position()} steps\n")

            identified_wavelength = None
            identified_center_px  = None
            result_frame          = None

            for target_steps, known_wavelength in SEARCH_POSITIONS:
                print(f"\n  ── Searching at position {target_steps} steps "
                      f"({'wavelength unknown' if known_wavelength is None else f'{known_wavelength:.3f} nm'}) ──")

                # Move spectrometer to target position
                success = triax_move_to_position(target_steps)
                if not success:
                    print(f"  Move to {target_steps} failed — trying next position.")
                    continue

                # Wait for spectrometer to settle
                time.sleep(1.0)

                # Acquire and fit
                fit_result, full_frame = acquire_and_fit()

                if fit_result is not None:
                    center, center_err, fwhm, r2 = fit_result

                    if known_wavelength is not None:
                        identified_wavelength = known_wavelength
                        identified_center_px  = center
                        result_frame          = full_frame
                        print(f"\n  ── Wavelength identified ─────────────────────────")
                        print(f"  TRIAX position   : {target_steps} steps")
                        print(f"  Known wavelength : {known_wavelength:.3f} nm")
                        print(f"  Centre pixel     : {center:.4f} ± {center_err:.4f} px")
                        print(f"  FWHM             : {fwhm:.4f} px")
                        print(f"  R²               : {r2:.6f}")
                        print(f"  ─────────────────────────────────────────────────\n")
                    else:
                        # Unknown wavelength position — report pixel only
                        result_frame = full_frame
                        print(f"\n  ── Peak found at unknown wavelength position ─────")
                        print(f"  TRIAX position   : {target_steps} steps")
                        print(f"  Centre pixel     : {center:.4f} ± {center_err:.4f} px")
                        print(f"  FWHM             : {fwhm:.4f} px")
                        print(f"  R²               : {r2:.6f}")
                        print(f"  Note: wavelength at this position is not calibrated.")
                        print(f"  ─────────────────────────────────────────────────\n")

                    break

                else:
                    print(f"  No laser peak found at {target_steps} steps — "
                          f"moving to next search position.")

            if fit_result is None:
                print("\n  No laser peak found at any search position.")
                print("  Check that the laser is on and within the detector range.")

            # ── Display result ─────────────────────────────────────────────────
            if result_frame is not None:
                fig_wl, (ax_wl_img, ax_wl_spec) = plt.subplots(1, 2, figsize=(12, 4))
                fig_wl.suptitle("Wavelength Identification Result", fontsize=10)

                ax_wl_img.imshow(result_frame, cmap='gray', aspect='auto')
                ax_wl_img.axhline(y=550, color='cyan', linewidth=1,
                                  linestyle='--', alpha=0.8, label='ROI top')
                ax_wl_img.axhline(y=650, color='cyan', linewidth=1,
                                  linestyle='--', alpha=0.8, label='ROI bottom')
                ax_wl_img.axvline(x=10,   color='lime', linewidth=1,
                                  linestyle=':', alpha=0.8)
                ax_wl_img.axvline(x=1023, color='lime', linewidth=1,
                                  linestyle=':', alpha=0.8)
                ax_wl_img.set_title("CCD Image")
                ax_wl_img.set_xlabel("X pixel")
                ax_wl_img.set_ylabel("Y pixel")
                ax_wl_img.legend(fontsize=7)

                region     = result_frame[550:650, 10:1024]
                x_spectrum = region.mean(axis=0)
                x_pixels   = np.arange(10, 1024)

                ax_wl_spec.plot(x_pixels, x_spectrum, color='steelblue',
                                linewidth=1, label='X spectrum')

                if fit_result is not None:
                    center, center_err, fwhm, r2 = fit_result
                    x_fine = np.linspace(x_pixels[0], x_pixels[-1], 500)
                    y_fine = voigt(x_fine, *[
                        x_spectrum.max() - float(np.percentile(x_spectrum, 10)),
                        center,
                        fwhm / 2.355,
                        fwhm / 2.0,
                        float(np.percentile(x_spectrum, 10))
                    ])
                    ax_wl_spec.axvline(x=center, color='gold', linewidth=1,
                                       linestyle=':', alpha=0.8, label=f'Centre: {center:.2f} px')

                    title = (f"Voigt fit  |  Centre: {center:.4f} ± {center_err:.4f} px  |  "
                             f"R²: {r2:.4f}")
                    if identified_wavelength is not None:
                        title += f"\nIdentified wavelength: {identified_wavelength:.3f} nm"
                    ax_wl_spec.set_title(title, fontsize=8)

                ax_wl_spec.set_xlabel("X pixel")
                ax_wl_spec.set_ylabel("Mean intensity (counts)")
                ax_wl_spec.grid(True, alpha=0.3)
                ax_wl_spec.legend(fontsize=7)
                fig_wl.tight_layout(rect=[0, 0, 1, 0.93])
                plt.show()

            triax.close()
            print("  TRIAX connection closed.")




    # --- Invalid Input ---
    else:
        print("Invalid choice. Please enter 1, 2, 3, or 4.")

finally:
    cam.close()
    print("Camera connection closed.")

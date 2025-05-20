import sys
if __name__ == "__main__":
    sys.path.insert(0, '..')
    sys.path.insert(0, '.')
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QPlainTextEdit,
    QFrame, QCheckBox, QSplitter, QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QMetaObject, QTimer, pyqtSlot
from PyQt5.QtWidgets import QProgressBar


from acquisitioncontrol.acqcontrol import AcquisitionControl
import sys
import traceback
import time
import threading
import logging

from logging_utils import QtLogHandler


def run_in_thread_and_refresh(func):
    """
    Decorator that runs `func(self, *args, **kwargs)` in a daemon
    thread and, when it finishes, schedules self.refresh_ui() on
    the Qt main loop.
    """
    def wrapper(self, *args, **kwargs):
        def target():
            try:
                func(self, *args, **kwargs)
            finally:
                pass
                # Schedule refresh_ui() back on the GUI thread
                QMetaObject.invokeMethod(self,
                                         "refresh_ui",
                                         Qt.QueuedConnection)
        threading.Thread(target=target, daemon=True).start()

    return wrapper


# Global exception hook to catch unhandled exceptions in the GUI
# def exception_hook(exc_type, exc_value, exc_tb):
#     """
#     Catch unhandled exceptions and write the full traceback to stderr.
#     """
#     tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
#     # Write to stderr, which is redirected to the GUI console
#     try:
#         sys.stderr.write(tb_text)
#     except Exception:
#         # Fallback to default handler if console not available
#         sys.__excepthook__(exc_type, exc_value, exc_tb)

# # Install the exception hook
# sys.excepthook = exception_hook


# --- Command line input with history ---
class CommandLineEdit(QLineEdit):
    enter_pressed = pyqtSignal(str)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history = []
        self.history_index = -1
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            text = self.text().strip()
            if text:
                self.history.append(text)
                self.history_index = len(self.history)
                self.enter_pressed.emit(text)
                self.clear()
        elif event.key() == Qt.Key_Up:
            if self.history and self.history_index > 0:
                self.history_index -= 1
                self.setText(self.history[self.history_index])
        elif event.key() == Qt.Key_Down:
            if self.history and self.history_index < len(self.history) - 1:
                self.history_index += 1
                self.setText(self.history[self.history_index])
        else:
            super().keyPressEvent(event)

# --- Text console for stdout/stderr ---
class TextConsole(QPlainTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
    def write(self, text):
        self.appendPlainText(text.strip())
    def flush(self):
        pass

# --- Main Application Window ---
class MainWindow(QMainWindow):
    scan_complete_signal = pyqtSignal()
    progress_update_signal = pyqtSignal(int)

    def __init__(self, acq_ctrl, interface):
        super().__init__()
        self.acq_ctrl = acq_ctrl
        self.interface = interface
        self.setWindowTitle("Acquisition GUI")
        self.resize(1200, 800)
        self.param_entries = {}
        self.start_pos = acq_ctrl.start_position()
        self.stop_pos = acq_ctrl.stop_position()
        self.scan_mode = acq_ctrl.scan_mode
        self.separate_resolution = acq_ctrl.separate_resolution
        self.z_scan = acq_ctrl.z_scan

        self.scanning = False
        self.cancel_event = threading.Event()
        self.scan_complete_signal.connect(self.scan_finished)
        self.progress_update_signal.connect(self.update_progress_bar)

        self.init_ui()
        self.refresh_ui()

                # Create a new QtLogHandler specific to this GUI

        # 1) instantiate a fresh handler, make MainWindow its parent
        self.qt_handler = QtLogHandler(parent=self)

        # 2) format it & hook it up
        self.qt_handler.setFormatter(logging.Formatter('%(message)s'))
        self.qt_handler.logMessage.connect(self.console.write)

        # 3) attach to the central logger
        central = self.interface.logger  # your 'instrument' logger
        central.addHandler(self.qt_handler)

        self.logger = self.interface.logger

    # def _append_log(self, txt: str):
    #     self.console.append(txt)

    # Helper to send commands to CLI interface
    @run_in_thread_and_refresh
    def send_cli_command(self, cmd):
        self.logger.cmd(f"{cmd}")
        result = self.interface.process_gui_command(cmd)
        if result is not None:
            self.logger.info(result)

    def confirm_scan(self, scan_sequence):
        '''Create a popup window to confirm the scan sequence.'''
        estimated_time = self.acq_ctrl.update_scan_estimate()

        # Format the scan sequence for display
        scan_details = (
            f"Scan mode: {self.acq_ctrl.scan_mode}\n"
            f"Start position: {self.acq_ctrl.start_position()}\n"
            f"Stop position: {self.acq_ctrl.stop_position()}\n"
            f"Wavelengths: {self.acq_ctrl.scan_wavelengths}\n"
            f"Polarizations in: {self.acq_ctrl.scan_polarizations_in}\n"
            f"Polarizations out: {self.acq_ctrl.scan_polarizations_out}\n"
            f"Estimated time: {estimated_time['duration']:.2f} {estimated_time['units']}\n"
            f"Acquisition time: {self.acq_ctrl.general_parameters['acquisition_time']} seconds\n"
            f"Frames per step: {self.acq_ctrl.general_parameters['n_frames']}\n"
            f"Laser power: {self.acq_ctrl.general_parameters['laser_power']} mW\n"
            f"Filename: {self.acq_ctrl.general_parameters['filename']}\n"
        )

        # Create a message box
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Confirm Scan")
        msg_box.setText("Please confirm the scan parameters:")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Ok)
        msg_box.setDetailedText(scan_details)
        msg_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        msg_box.setStyleSheet("QMessageBox { min-width: 400px; }")
        # Show the message box and wait for user response
        result = msg_box.exec_()
        if result == QMessageBox.Ok:
            # User confirmed the scan
            self.logger.info("Scan confirmed.")
            return True
        else:
            # User cancelled the scan
            self.logger.info("Scan cancelled.")
            return False

    def cancel_scan(self):
        """
        Cancel the scan. This method is called when the user clicks the "Cancel Scan" button.
        """
        self.cancel_event.set()
        # self.scan_status.config(text="Scan cancelled.")
        # Re-enable buttons
        for btn in self.control_buttons:
            btn.setEnabled(True)
        self.btn_cancel_scan.setEnabled(False)
    
    def initiate_scan(self):
        """
        Called when the user clicks 'Run Scan'. Builds the scan, asks for confirmation,
        then launches the scan in a background thread.
        """
        scan_sequence = self.acq_ctrl.build_scan_sequence()
        if not self.confirm_scan(scan_sequence):
            return
        
        self.acq_ctrl.prepare_acquisition_params()
        
        self.cancel_event.clear()
        self.set_controls_enabled(False)
        self.btn_cancel_scan.setEnabled(True)
        self.progress_bar.setValue(0)
        self.refresh_ui()
        self.scanning = True
        self.start_time = time.time()

        def thread_safe_progress_callback(value):
            self.progress_update_signal.emit(value)
        # wrapper to handel scan and emit signal to end
        def run_and_emit():
            self.acq_ctrl.acquire_scan(
                self.cancel_event,
                self.update_status,
                thread_safe_progress_callback
            )
            self.scan_complete_signal.emit()  # emits safely from any thread

        self.scan_thread = threading.Thread(target=run_and_emit)
        self.scan_thread.start()

    def scan_finished(self):
        self.scanning = False
        self.set_controls_enabled(True)
        self.update_status("Scan finished.")
        self.progress_bar.setValue(100)
        self.refresh_ui()

    def set_controls_enabled(self, enabled: bool):
        for btn in self.control_buttons:
            btn.setEnabled(enabled)
        self.btn_cancel_scan.setEnabled(False if enabled else True)


    def update_status(self, status):
        '''UI callback to update the status of the scan.'''
        self.logger.info(status)
    

    def update_progress(self, current_steps, total_steps, start_time):
        '''Updates the progress bar and status label.'''
        pass
        # bar_length = 20
        # filled_length = int(bar_length * current_steps // total_steps)
        # bar = '[' + '#' * filled_length + ' ' * (bar_length - filled_length) + ']'
        # self.progress_bar.config(text=bar)
        # elapsed = time.time() - start_time
        # estimated_remaining = (elapsed / current_steps) * (total_steps - current_steps)
        # # self.estimate_label.config(text=f"Estimated remaining: {estimated_remaining:.1f}s")
        # self.elapsed_label.config(text=f"Elapsed: {elapsed:.1f}s")
    
    def build_param_tabs(self):
        """
        Populate self.tabs with one tab per parameter dictionary.
        Each tab is a QWidget containing a vertical layout with form fields.
        """
        # Clear any existing tabs
        self.tabs.clear()

        # Define the sections and the corresponding dicts
        sections = {
            'General':      self.acq_ctrl.general_parameters,
            'Motion':       self.acq_ctrl.motion_parameters,
            'Wavelength':   self.acq_ctrl.wavelength_parameters,
            'Polarization': self.acq_ctrl.polarization_parameters
        }

        for name, params in sections.items():
            # Create a new page for this tab
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)

            # Build fields based on whether values are nested dicts or flat
            self.build_section(tab_layout, params, name.lower())

            # Add the tab to the QTabWidget
            self.tabs.addTab(tab, name)


    def build_section(self, parent_layout, parameters: dict, section_prefix: str):
        """
        Auto-generate QLineEdits for a given parameters dict.
        - Flat dict → one QFormLayout
        - Nested dict → one QGroupBox + QFormLayout per subgroup
        """
        # Flat parameters?
        if all(not isinstance(val, dict) for val in parameters.values()):
            form_layout = QFormLayout()
            for param_name, param_value in parameters.items():
                line_edit = QLineEdit(str(param_value))
                form_layout.addRow(f"{param_name}:", line_edit)

                # Store widget + type under a unique full_key
                full_key = f"{section_prefix}.{param_name}"
                self.param_entries[full_key] = (line_edit, type(param_value))

                # Capture full_key in the lambda default
                line_edit.editingFinished.connect(
                    lambda fkey=full_key: self._on_field_edited(fkey)
                )

            parent_layout.addLayout(form_layout)

        # Nested parameters
        else:
            for subgroup_name, subgroup_params in parameters.items():
                group_box = QGroupBox(subgroup_name.capitalize())
                subgroup_form = QFormLayout()

                for param_name, param_value in subgroup_params.items():
                    line_edit = QLineEdit(str(param_value))
                    subgroup_form.addRow(f"{param_name}:", line_edit)

                    full_key = f"{section_prefix}.{subgroup_name}.{param_name}"
                    self.param_entries[full_key] = (line_edit, type(param_value))
                    line_edit.editingFinished.connect(
                        lambda fkey=full_key: self._on_field_edited(fkey)
                    )

                group_box.setLayout(subgroup_form)
                parent_layout.addWidget(group_box)


    def _on_field_edited(self, entry_key: str):
        """
        Called when any QLineEdit finishes editing.
        Parses entry_key like "motion.start_position.x" to
        update the corresponding value in acq_ctrl.
        """
        # Split e.g. ["motion","start_position","x"]
        key_parts = entry_key.split('.')

        # e.g. "motion" → "motion_parameters"
        section_attr = f"{key_parts[0]}_parameters"
        target_dict = getattr(self.acq_ctrl, section_attr)

        # Drill down through any nested dicts (all but last part)
        for nested_key in key_parts[1:-1]:
            target_dict = target_dict[nested_key]

        # Final part is the actual parameter name
        param_name = key_parts[-1]

        # Read the new text and cast to the original type
        widget, original_type = self.param_entries[entry_key]
        text = widget.text()
        # first, try to convert
        try:
            if original_type is float:
                new_value = float(text)
            elif original_type is int:
                new_value = int(text)
            else:
                new_value = text

        except ValueError:
            # conversion failed → mark widget red
            widget.setStyleSheet("background-color: #ffcccc;")  # light red
            return

        # conversion succeeded → mark widget green
        widget.setStyleSheet("background-color: #ccffcc;")  # light green
        # Write it back
        target_dict[param_name] = new_value

        # self.logger.info(self.acq_ctrl.general_parameters)
        # self.logger.info(self.acq_ctrl.motion_parameters)
        self.acq_ctrl.save_config()
        self.refresh_ui()

    @pyqtSlot()
    def refresh_ui(self):
        # Update all parameter fields
        for fullkey, (line_edit, _) in self.param_entries.items():
            parts = fullkey.split(".")
            section = parts[0] + "_parameters"
            d = getattr(self.acq_ctrl, section)
            for p in parts[1:]:
                d = d[p]
            line_edit.setText(str(d))



        # Update labels for mode, positions, and estimate
        scan_time = self.acq_ctrl.update_scan_estimate()
        self.btn_mode_toggle.setText(f"Mode: {self.acq_ctrl.scan_mode.capitalize()}")
        self.lbl_mode.setText(self.acq_ctrl.scan_mode.capitalize())
        self.lbl_start.setText(self.acq_ctrl.start_position())
        self.lbl_stop.setText(self.acq_ctrl.stop_position())
        self.lbl_est.setText(f"{scan_time['duration']:.2f} {scan_time['units']}")

        # Stage position update
        stage_pos = self.acq_ctrl.current_stage_coordinates
        self.lbl_stage_x.setText(f"{stage_pos[0]:.2f}")
        self.lbl_stage_y.setText(f"{stage_pos[1]:.2f}")
        self.lbl_stage_z.setText(f"{stage_pos[2]:.2f}")

        # instrument state update
        self.lbl_laser.setText(f"{self.interface.microscope.report_laser_wavelength:.2f} nm")
        self.lbl_grating.setText(f"{self.interface.microscope.report_grating_wavelength:.2f} nm")
        self.lbl_monochromator.setText(f"{self.interface.microscope.report_monochromator_wavelength:.2f} nm")
        self.lbl_spectrometer.setText(f"{self.interface.microscope.report_spectrometer_wavelength:.2f} nm")
        # self.lbl_entrance_slit.setText(f"{self.interface.microscope.report_entrance_slit:.2f} nm")

        # self.update_instrument_state()
        # self.set_start()   # or otherwise update start/stop labels
        # self.set_stop()


    def init_ui(self):
        central = QWidget()
        main_layout = QHBoxLayout(central)
        self.setCentralWidget(central)

        # --- Left: Acquisition Control ---
        self.tabs = QTabWidget()
        self.build_param_tabs()

        acq_group = QGroupBox("Acquisition Control")
        ag_layout = QVBoxLayout()

        # Scan mode toggle
        self.btn_mode_toggle = QPushButton("Mode: Map")
        self.btn_mode_toggle.clicked.connect(lambda: self.send_cli_command('scanmode'))
        ag_layout.addWidget(self.btn_mode_toggle)

        # Checkboxes
        self.chk_sep_res = QCheckBox("Separate Resolution")
        self.chk_sep_res.setChecked(False)
        self.chk_sep_res.toggled.connect(lambda en: self.send_cli_command(f'nyi {en}'))
        ag_layout.addWidget(self.chk_sep_res)

        self.chk_z_scan = QCheckBox("Enable Z Scan")
        self.chk_z_scan.setChecked(False)
        self.chk_z_scan.toggled.connect(lambda en: self.send_cli_command(f'nyi {en}'))
        ag_layout.addWidget(self.chk_z_scan)

        ag_layout.addWidget(self.tabs)
        acq_group.setLayout(ag_layout)
        main_layout.addWidget(acq_group, 1)

        # --- Right: Instrument Control + State + Others ---
        right_layout = QVBoxLayout()

        # --- Top Button Row: Acquisition Actions ---
        top_button_layout = QHBoxLayout()

        # Left button group
        left_btn_layout = QVBoxLayout()
        self.btn_run_cont = QPushButton("Run Cont.")
        self.btn_run_cont.setStyleSheet("background-color: lightgray;")
        # self.btn_run_cont.clicked.connect(lambda: self.send_cli_command("run"))
        self.btn_run_cont.clicked.connect(lambda: self.send_cli_command("run"))

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet("background-color: lightgray;")
        self.btn_stop.clicked.connect(lambda: self.send_cli_command("stop"))

        self.btn_acquire = QPushButton("Acquire")
        self.btn_acquire.setStyleSheet("background-color: lightgray;")
        self.btn_acquire.clicked.connect(lambda: self.send_cli_command("acquire"))

        left_btn_layout.addWidget(self.btn_run_cont)
        left_btn_layout.addWidget(self.btn_stop)
        left_btn_layout.addWidget(self.btn_acquire)

        # Right button group
        right_btn_layout = QVBoxLayout()
        self.btn_run_scan = QPushButton("Run Scan")
        self.btn_run_scan.setStyleSheet("background-color: lightgray;")
        self.btn_run_scan.clicked.connect(lambda: self.initiate_scan())

        self.btn_cancel_scan = QPushButton("Cancel Scan")
        self.btn_cancel_scan.setStyleSheet("background-color: lightgray;")
        self.btn_cancel_scan.clicked.connect(lambda: self.cancel_scan())

        right_btn_layout.addWidget(self.btn_run_scan)
        right_btn_layout.addWidget(self.btn_cancel_scan)

        top_button_layout.addLayout(left_btn_layout)
        top_button_layout.addSpacing(20)
        top_button_layout.addLayout(right_btn_layout)

        # Add to the top of the right_layout
        right_layout.addLayout(top_button_layout)

        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        # Controls and state side-by-side
        ctrl_state_layout = QHBoxLayout()

        # Instrument Control
        instrument_group = QGroupBox("Instrument Control")
        ig_layout = QHBoxLayout()
        self.btn_set_home = QPushButton("Set Home")
        self.btn_set_home.clicked.connect(lambda: self.send_cli_command('stagehome'))
        self.btn_set_start = QPushButton("Set Start")
        self.btn_set_start.clicked.connect(lambda: self.send_cli_command('setstart'))
        self.btn_set_stop = QPushButton("Set Stop")
        self.btn_set_stop.clicked.connect(lambda: self.send_cli_command('setstop'))
        ig_layout.addWidget(self.btn_set_home)
        ig_layout.addWidget(self.btn_set_start)
        ig_layout.addWidget(self.btn_set_stop)
        instrument_group.setLayout(ig_layout)

        ctrl_state_layout.addWidget(instrument_group)

        # Instrument State
        state_group = QGroupBox("Instrument State")
        sg_form = QFormLayout()
        self.lbl_laser = QLabel("N/A")
        self.lbl_grating = QLabel("N/A")
        self.lbl_monochromator = QLabel("N/A")
        self.lbl_spectrometer = QLabel("N/A")
        self.lbl_entrance_slit = QLabel("N/A")
        sg_form.addRow("Laser wavelength:", self.lbl_laser)
        sg_form.addRow("Grating wavelength:", self.lbl_grating)
        sg_form.addRow("Monochromator wavelength:", self.lbl_monochromator)
        sg_form.addRow("Spectrometer wavelength:", self.lbl_spectrometer)
        sg_form.addRow("Entrance slit:", self.lbl_entrance_slit)
        state_group.setLayout(sg_form)

        ctrl_state_layout.addWidget(state_group)

        right_layout.addLayout(ctrl_state_layout)

        # Scan positions / stage positions
        pos_group_layout = QHBoxLayout()

        # Scan pos
        scan_pos_group = QGroupBox("Positions / Estimate")
        pl = QFormLayout()
        self.lbl_mode = QLabel(self.scan_mode.capitalize())
        self.lbl_start = QLabel(str(self.start_pos))
        self.lbl_stop = QLabel(str(self.stop_pos))
        self.lbl_est = QLabel(self.get_estimated_time())
        pl.addRow("Mode:", self.lbl_mode)
        pl.addRow("Start Pos:", self.lbl_start)
        pl.addRow("Stop Pos", self.lbl_stop)
        pl.addRow("Estimated Runtime:", self.lbl_est)
        scan_pos_group.setLayout(pl)
        pos_group_layout.addWidget(scan_pos_group)

        # Stage pos
        stage_pos_group = QGroupBox("Stage Position")
        pl2 = QFormLayout()
        self.lbl_stage_x = QLabel(str(self.interface.microscope.stage_positions_microns['x']))
        self.lbl_stage_y = QLabel(str(self.interface.microscope.stage_positions_microns['y']))
        self.lbl_stage_z = QLabel(str(self.interface.microscope.stage_positions_microns['z']))
        pl2.addRow("X:", self.lbl_stage_x)
        pl2.addRow("Y:", self.lbl_stage_y)
        pl2.addRow("Z:", self.lbl_stage_z)
        stage_pos_group.setLayout(pl2)

        pos_group_layout.addWidget(stage_pos_group)
        right_layout.addLayout(pos_group_layout)

        # Console
        console_group = QGroupBox("Console")
        cl = QVBoxLayout()
        self.console = TextConsole()
        cl.addWidget(self.console)
        self.cmd_input = CommandLineEdit()
        self.cmd_input.enter_pressed.connect(self.handle_command)
        cl.addWidget(self.cmd_input)
        console_group.setLayout(cl)

        # Plot placeholder
        plot_group = QGroupBox("Plot Area")
        pfl = QVBoxLayout()
        plot_frame = QFrame()
        plot_frame.setFrameStyle(QFrame.Box | QFrame.Plain)
        plot_frame.setLineWidth(1)
        pfl.addWidget(plot_frame)
        plot_group.setLayout(pfl)

        # Splitter to separate console and plot
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(console_group)
        splitter.addWidget(plot_group)
        splitter.setSizes([400, 200])

        right_layout.addWidget(splitter, 1)

        main_layout.addLayout(right_layout, 1)

        # Redirect stdout/stderr
        # sys.stdout = self.console
        # sys.stderr = self.console

        # Disable all buttons initially

        # Store for future control
        self.control_buttons = [
            self.btn_run_cont,
            self.btn_stop,
            self.btn_acquire,
            self.btn_run_scan,
            self.btn_mode_toggle,
            self.btn_set_home,
            self.btn_set_start,
            self.btn_set_stop,
            # self.btn_cancel_scan,
        ]

        # initially disable scan cancel
        self.btn_cancel_scan.setEnabled(False)

    def update_progress_bar(self, value: int):
        self.progress_bar.setValue(value)

    def get_estimated_time(self):
        scan_duration = self.acq_ctrl.update_scan_estimate()

        return f"{scan_duration['duration']} {scan_duration['units']}"

    def handle_command(self, text):
        self.send_cli_command(text)

    def closeEvent(self, event):
        # restore the real streams
        # sys.stdout = self._orig_stdout
        # sys.stderr = self._orig_stderr
                # Disconnect the slot
        try:
            self.qt_handler.logMessage.disconnect(self.console.write)
        except TypeError:
            pass  # already disconnected
        except Exception as e:
            self.logger.error(f"Error disconnecting log handler: {e}")
            traceback.print_exc()

        # (Optional) remove the handler so no Qt work happens at all
        self.interface.logger.removeHandler(self.qt_handler)

        super().closeEvent(event)




if __name__ == "__main__":
    import os
    from acquisitioncontrol.simulation import DummyMicroscope, DummyCLI
    print("### Running Simulated GUI ###")
    sys.path.insert(0, os.path.dirname(__file__))
    interface = DummyCLI()
    app = QApplication(sys.argv)
    acq_ctrl = AcquisitionControl(interface)
    interface.acq_ctrl = acq_ctrl
    main_window = MainWindow(acq_ctrl, interface)
    main_window.show()
    sys.exit(app.exec_())
import sys
if __name__ == "__main__":
    sys.path.insert(0, '..')
    sys.path.insert(0, '.')
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QPlainTextEdit,
    QFrame, QCheckBox, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal


from acquisitioncontrol.acqcontrol import AcquisitionControl
import sys
import traceback

# Global exception hook to catch unhandled exceptions in the GUI
def exception_hook(exc_type, exc_value, exc_tb):
    """
    Catch unhandled exceptions and write the full traceback to stderr.
    """
    tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    # Write to stderr, which is redirected to the GUI console
    try:
        sys.stderr.write(tb_text)
    except Exception:
        # Fallback to default handler if console not available
        sys.__excepthook__(exc_type, exc_value, exc_tb)

# Install the exception hook
sys.excepthook = exception_hook


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
        self.appendPlainText(text)
    def flush(self):
        pass

# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self, acq_ctrl, interface):
        super().__init__()
        self.acq_ctrl = acq_ctrl
        self.interface = interface
        self.setWindowTitle("Acquisition GUI")
        self.resize(1200, 800)
        self.param_entries = {}
        self.start_pos = acq_ctrl.start_position
        self.stop_pos = acq_ctrl.stop_position
        self.scan_mode = acq_ctrl.scan_mode
        self.separate_resolution = acq_ctrl.separate_resolution
        self.z_scan = acq_ctrl.z_scan
        self.init_ui()

    # Helper to send commands to CLI interface
    def send_cli_command(self, cmd):
        print(f">>> {cmd}")
        result = self.interface.process_gui_command(cmd)
        if result:
            print(result)
        
        self.refresh_ui()
    
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

        # print(self.acq_ctrl.general_parameters)
        # print(self.acq_ctrl.motion_parameters)
        self.acq_ctrl.save_config()


    def refresh_ui(self):
        # update all parameter textboxes
        for fullkey, (line_edit, _) in self.param_entries.items():
            parts = fullkey.split(".")
            section = parts[0] + "_parameters"
            d = getattr(self.acq_ctrl, section)
            for p in parts[1:]:
                d = d[p]
            line_edit.setText(str(d))
        # also refresh dynamic labels, instrument state, etc.
        self.lbl_mode.setText(self.acq_ctrl.button_parameters['scan_mode'].capitalize())
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
        self.toggle_btn = QPushButton("Mode: Map")
        self.toggle_btn.clicked.connect(lambda: self.send_cli_command('toggle_scan_mode'))
        ag_layout.addWidget(self.toggle_btn)

        # Checkboxes
        self.chk_sep_res = QCheckBox("Separate Resolution")
        self.chk_sep_res.setChecked(False)
        self.chk_sep_res.toggled.connect(lambda en: self.send_cli_command(f'sep_res {en}'))
        ag_layout.addWidget(self.chk_sep_res)

        self.chk_z_scan = QCheckBox("Enable Z Scan")
        self.chk_z_scan.setChecked(False)
        self.chk_z_scan.toggled.connect(lambda en: self.send_cli_command(f'z_scan {en}'))
        ag_layout.addWidget(self.chk_z_scan)

        ag_layout.addWidget(self.tabs)
        acq_group.setLayout(ag_layout)
        main_layout.addWidget(acq_group, 1)

        # --- Right: Instrument Control + State + Others ---
        right_layout = QVBoxLayout()

        # Controls and state side-by-side
        ctrl_state_layout = QHBoxLayout()

        # Instrument Control
        instrument_group = QGroupBox("Instrument Control")
        ig_layout = QHBoxLayout()
        btn_set_home = QPushButton("Set Home")
        btn_set_home.clicked.connect(lambda: self.send_cli_command('stagehome'))
        btn_set_start = QPushButton("Set Start")
        btn_set_start.clicked.connect(lambda: self.send_cli_command('startpos'))
        btn_set_stop = QPushButton("Set Stop")
        btn_set_stop.clicked.connect(lambda: self.send_cli_command('endpos'))
        ig_layout.addWidget(btn_set_home)
        ig_layout.addWidget(btn_set_start)
        ig_layout.addWidget(btn_set_stop)
        instrument_group.setLayout(ig_layout)

        ctrl_state_layout.addWidget(instrument_group)

        # Instrument State
        state_group = QGroupBox("Instrument State")
        sg_form = QFormLayout()
        self.lbl_laser = QLabel("N/A")
        self.lbl_grating = QLabel("N/A")
        self.lbl_monochromator = QLabel("N/A")
        self.lbl_spectrometer = QLabel("N/A")
        sg_form.addRow("Laser wavelength:", self.lbl_laser)
        sg_form.addRow("Grating wavelength:", self.lbl_grating)
        sg_form.addRow("Monochromator wavelength:", self.lbl_monochromator)
        sg_form.addRow("Spectrometer wavelength:", self.lbl_spectrometer)
        state_group.setLayout(sg_form)

        ctrl_state_layout.addWidget(state_group)

        right_layout.addLayout(ctrl_state_layout)

        # Scan positions / stage positions
        pos_group_layout = QHBoxLayout()

        # Scan pos
        scan_pos_group = QGroupBox("Positions / Estimate")
        pl = QFormLayout()
        self.lbl_mode = QLabel(self.scan_mode.capitalize())
        self.lbl_start = QLabel("Start: (0.0, 0.0, 0.0)")
        self.lbl_stop = QLabel("Stop: (0.0, 0.0, 0.0)")
        self.lbl_est = QLabel("Estimated runtime: 0.0s")
        pl.addRow("Mode:", self.lbl_mode)
        pl.addRow("Start Pos:", self.lbl_start)
        pl.addRow("Stop Pos", self.lbl_stop)
        pl.addRow("Estimated Time:", self.lbl_est)
        scan_pos_group.setLayout(pl)
        pos_group_layout.addWidget(scan_pos_group)

        # Stage pos
        stage_pos_group = QGroupBox("Stage Position")
        pl2 = QFormLayout()
        self.lbl_stage_x = QLabel(str(self.acq_ctrl.microscope.stage_positions_microns['x']))
        self.lbl_stage_y = QLabel(str(self.acq_ctrl.microscope.stage_positions_microns['y']))
        self.lbl_stage_z = QLabel(str(self.acq_ctrl.microscope.stage_positions_microns['z']))
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
        # right_layout.addWidget(console_group, 1)

        # Plot placeholder
        plot_group = QGroupBox("Plot Area")
        pfl = QVBoxLayout()
        plot_frame = QFrame()
        plot_frame.setFrameStyle(QFrame.Box | QFrame.Plain)
        plot_frame.setLineWidth(1)
        pfl.addWidget(plot_frame)
        plot_group.setLayout(pfl)
        # right_layout.addWidget(plot_group, 1)

        # Splitter to separate console and plot 

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(console_group)
        splitter.addWidget(plot_group)
        splitter.setSizes([400, 200])   # initial pixel sizes: console 400px, plot 200px

        right_layout.addWidget(splitter, 1)

        main_layout.addLayout(right_layout, 1)

        # Redirect stdout/stderr
        sys.stdout = self.console
        sys.stderr = self.console

    def handle_command(self, text):
        self.send_cli_command(text)

    def closeEvent(self, event):
        # restore the real streams
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        super().closeEvent(event)



if __name__ == "__main__":
    import os
    from acquisitioncontrol.simulation import DummyMicroscope, DummyCLI
    print("### Running Simulated GUI ###")
    sys.path.insert(0, os.path.dirname(__file__))
    microscope = DummyMicroscope()
    app = QApplication(sys.argv)
    acq_ctrl = AcquisitionControl(microscope=microscope)
    microscope.acquisition_control = acq_ctrl
    main_window = MainWindow(acq_ctrl, DummyCLI(microscope))
    main_window.show()
    sys.exit(app.exec_())
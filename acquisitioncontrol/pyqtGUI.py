import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QPlainTextEdit,
    QFrame, QCheckBox, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal


from .acqcontrol import AcquisitionControl
from .simulation import DummyMicroscope
import sys
import traceback

# Global exception hook to catch unhandled exceptions in the GUI
def exception_hook(exc_type, exc_value, exc_tb):
    # Format traceback
    tb = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    # Show error dialog
    QMessageBox.critical(None, "Unhandled Exception", tb)
    # Call the default hook for logging
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
    def __init__(self, acq_ctrl, cli_interface):
        super().__init__()
        self.acq_ctrl = acq_ctrl
        self.cli = cli_interface
        self.setWindowTitle("Acquisition GUI")
        self.resize(1200, 800)
        self.param_entries = {}
        self.start_pos = [0,0,0]
        self.stop_pos = [0,0,0]
        self.scan_mode = acq_ctrl.scan_mode
        self.separate_resolution = acq_ctrl.separate_resolution
        self.z_scan = acq_ctrl.z_scan
        self.init_ui()

    # Helper to send commands to CLI interface
    def send_cli_command(self, cmd):
        print(f">>> {cmd}")
        result = self.cli.process_gui_command(cmd)
        if result:
            print(result)
    
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


    def build_section(self, layout, param_dict, prefix):
        """
        Given a layout and a dict, auto-generate QLineEdits.
        - If values are simple (not dict), lay them out in a QFormLayout.
        - If values are nested dicts, create a QGroupBox per subgroup.
        """
        # Check if every value is NOT a dict => flat form
        if all(not isinstance(v, dict) for v in param_dict.values()):
            form = QFormLayout()
            for key, val in param_dict.items():
                le = QLineEdit(str(val))
                form.addRow(key + ":", le)
                # Keep track for later retrieval
                # capture the original Python type
                expected_type = type(val)
                self.param_entries[f"{prefix}.{key}"] = (le, expected_type)
                le.editingFinished.connect(lambda p=prefix, k=key: self._on_field_edited(p, k))

            layout.addLayout(form)

        else:
            # Nested dict: one group per subgroup
            for subgroup, subdict in param_dict.items():
                gb = QGroupBox(subgroup.capitalize())
                form = QFormLayout()
                for key, val in subdict.items():
                    le = QLineEdit(str(val))
                    form.addRow(key + ":", le)
                    expected_type = type(val)
                    self.param_entries[f"{prefix}.{key}"] = (le, expected_type)
                    le.editingFinished.connect(lambda p=prefix, k=key: self._on_field_edited(p, k))
                gb.setLayout(form)
                layout.addWidget(gb)

    def _on_field_edited(self, full_key):
        '''Validate and update the parameter when a field is edited.'''
        # full_key might be "motion.start_position.x"
        
        # 1. Split into parts
        parts = full_key.split('.')  
        # parts = ["motion", "start_position", "x"]

        # 2. Determine which parameter dict to update
        #    The first part (e.g. "motion") corresponds to self.acq_ctrl.motion_parameters
        section_name = parts[0] + "_parameters"
        param_dict = getattr(self.acq_ctrl, section_name)
        # param_dict is now your 'motion_parameters' dict

        # 3. Drill down into nested dicts for all but the last key
        #    parts[1:-1] = ["start_position"]
        for subgroup_key in parts[1:-1]:
            param_dict = param_dict[subgroup_key]
        # Now param_dict is the dict for start_position, e.g. {'x': ..., 'y': ..., 'z': ...}

        # 4. The final part is the actual parameter name (e.g. "x")
        final_key = parts[-1]

        # 5. Convert the text to the right type (int, float, or str)
        text_value = self.param_entries[full_key][0].text()
        expected_type = self.param_entries[full_key][1]
        if expected_type is float:
            new_value = float(text_value)
        elif expected_type is int:
            new_value = int(text_value)
        else:
            new_value = text_value

        # 6. Write it back into the nested dict
        param_dict[final_key] = new_value

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
        self.lbl_mode.setText(self.acq_ctrl.general_parameters['scan_type'].capitalize())
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
        btn_set_home.clicked.connect(lambda: self.send_cli_command('home'))
        btn_set_start = QPushButton("Set Start")
        btn_set_start.clicked.connect(lambda: self.send_cli_command('set_start'))
        btn_set_stop = QPushButton("Set Stop")
        btn_set_stop.clicked.connect(lambda: self.send_cli_command('set_stop'))
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

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QPlainTextEdit,
    QFrame, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal

from acquisitioncontrol import AcquisitionControl
from simulation import DummyMicroscope


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
    def __init__(self, acq_ctrl):
        super().__init__()
        self.acq_ctrl = acq_ctrl
        self.setWindowTitle("Acquisition GUI")
        self.resize(1200, 800)
        self.param_entries = {}
        self.start_pos = [0,0,0]
        self.stop_pos = [0,0,0]
        self.scan_mode = 'map'
        self.init_ui()

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
        self.toggle_btn.clicked.connect(self.toggle_scan_mode)
        ag_layout.addWidget(self.toggle_btn)

        # Checkboxes
        self.chk_sep_res = QCheckBox("Separate Resolution")
        self.chk_sep_res.setChecked(False)
        self.chk_sep_res.toggled.connect(self.toggle_sep_res)
        ag_layout.addWidget(self.chk_sep_res)

        self.chk_z_scan = QCheckBox("Enable Z Scan")
        self.chk_z_scan.setChecked(False)
        self.chk_z_scan.toggled.connect(self.toggle_z_scan)
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
        btn_set_start = QPushButton("Set Start")
        btn_set_stop = QPushButton("Set Stop")
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
        pl = QFormLayout()
        self.lbl_stage_x = QLabel(str(self.acq_ctrl.x_position))
        self.lbl_stage_y = QLabel(str(self.acq_ctrl.y_position))
        self.lbl_stage_z = QLabel(str(self.acq_ctrl.z_position))
        pl.addRow("X:", self.lbl_stage_x)
        pl.addRow("Y:", self.lbl_stage_y)
        pl.addRow("Z:", self.lbl_stage_z) 
        stage_pos_group.setLayout(pl)

        pos_group_layout.addWidget(stage_pos_group)
        right_layout.addLayout(pos_group_layout)



        # Console
        console_group = QGroupBox("Console")
        cl = QVBoxLayout()
        self.console = TextConsole()
        cl.addWidget(self.console)
        self.cmd_input = CommandLineEdit()
        cl.addWidget(self.cmd_input)
        console_group.setLayout(cl)
        right_layout.addWidget(console_group, 1)

        # Plot placeholder
        plot_group = QGroupBox("Plot Area")
        pfl = QVBoxLayout()
        plot_frame = QFrame()
        plot_frame.setFrameStyle(QFrame.Box | QFrame.Plain)
        plot_frame.setLineWidth(1)
        pfl.addWidget(plot_frame)
        plot_group.setLayout(pfl)
        right_layout.addWidget(plot_group, 1)

        main_layout.addLayout(right_layout, 1)

        # Redirect stdout/stderr
        sys.stdout = self.console
        sys.stderr = self.console

        # Connect signals
        btn_set_start.clicked.connect(self.set_start)
        btn_set_stop.clicked.connect(self.set_stop)
        btn_set_home.clicked.connect(self.set_home_position)  # Dummy 
        self.cmd_input.enter_pressed.connect(self.handle_command)
    
    def toggle_scan_mode(self):
        new_mode = 'linescan' if self.scan_mode == 'map' else 'map'
        self.scan_mode = new_mode
        self.toggle_btn.setText(f"Mode: {new_mode.capitalize()}")
        print("Scan mode set to", new_mode)

    def toggle_sep_res(self, enabled):
        print("Separate resolution enabled:", enabled)
        # TODO: implement dynamic UI rebuild for resolution fields

    def toggle_z_scan(self, enabled):
        print("Z scan enabled:", enabled)
        # TODO: implement dynamic UI rebuild for Z fields

    def update_instrument_state(self):
        # Dummy update: replace with real instrument data
        self.lbl_laser.setText(f"{self.acq_ctrl.microscope.laser_wavelengths.get('l1',0.0):.1f} nm")
        self.lbl_grating.setText(f"{self.acq_ctrl.microscope.monochromator_wavelengths.get('g3',0.0):.1f} nm")
        self.lbl_monochromator.setText("500.0 nm")
        self.lbl_spectrometer.setText("1.23 nm")

    def build_param_tabs(self):
        sections = {
            'General':      self.acq_ctrl.general_parameters,
            'Motion':       self.acq_ctrl.motion_parameters,
            'Wavelength':   self.acq_ctrl.wavelength_parameters,
            'Polarization': self.acq_ctrl.polarization_parameters
        }
        for name, params in sections.items():
            tab = QWidget()
            vl = QVBoxLayout(tab)
            self.build_section(vl, params, name.lower())
            self.tabs.addTab(tab, name)

    def build_section(self, layout, param_dict, prefix):
        # Flat vs nested
        if all(not isinstance(v, dict) for v in param_dict.values()):
            form = QFormLayout()
            for k, v in param_dict.items():
                le = QLineEdit(str(v))
                form.addRow(k, le)
                self.param_entries[f"{prefix}.{k}"] = le
            layout.addLayout(form)
        else:
            for sub, subdict in param_dict.items():
                gb = QGroupBox(sub.capitalize())
                form = QFormLayout(gb)
                for k, v in subdict.items():
                    le = QLineEdit(str(v))
                    form.addRow(k, le)
                    self.param_entries[f"{prefix}.{sub}.{k}"] = le
                layout.addWidget(gb)

    def set_start(self):
        coords = self.acq_ctrl.current_stage_coordinates
        self.start_pos = coords
        self.label_start.setText(f"Start: ({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})")
        self.update_instrument_state()

    def set_stop(self):
        coords = self.acq_ctrl.current_stage_coordinates
        self.stop_pos = coords
        self.label_stop.setText(f"Stop: ({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})")
        self.label_est.setText(f"Estimated runtime: {self.acq_ctrl.estimate_scan_duration():.1f}s")
        self.update_instrument_state()

    def move_axis(self, axis):
        print(f"Moving axis {axis}")
        self.update_instrument_state()

    def set_home_position(self):
        print("Setting home position")


    def handle_command(self, text):
        print(f">>> {text}")


def main():
    app = QApplication(sys.argv)
    acq = AcquisitionControl(microscope=DummyMicroscope())
    w = MainWindow(acq)
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

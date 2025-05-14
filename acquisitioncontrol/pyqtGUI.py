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
    def __init__(self, acq_ctrl, cli_interface):
        super().__init__()
        self.acq_ctrl = acq_ctrl
        self.cli = cli_interface
        self.setWindowTitle("Acquisition GUI")
        self.resize(1200, 800)
        self.param_entries = {}
        self.start_pos = [0,0,0]
        self.stop_pos = [0,0,0]
        self.scan_mode = 'map'
        self.init_ui()

    # Helper to send commands to CLI interface
    def send_cli_command(self, cmd):
        print(f">>> {cmd}")
        result = self.cli.process_gui_command(cmd)
        if result:
            print(result)

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

    def handle_command(self, text):
        self.send_cli_command(text)

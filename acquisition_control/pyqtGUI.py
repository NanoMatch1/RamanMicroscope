# # pyqt_gui.py

# from PyQt5.QtWidgets import (
#     QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
#     QPushButton, QRadioButton, QButtonGroup, QTextEdit, QGroupBox
# )
# import sys

# class AcquisitionControlUI(QWidget):
#     def __init__(self):
#         super().__init__()
#         self.setWindowTitle("Acquisition Control (PyQt)")
#         self.init_ui()

#     def init_ui(self):
#         layout = QVBoxLayout()

#         # General Parameters
#         general_box = QGroupBox("General Parameters")
#         general_layout = QVBoxLayout()

#         self.acq_time_input = QLineEdit("1000.0")
#         self.filename_input = QLineEdit("default")

#         general_layout.addWidget(QLabel("Acquisition Time (ms):"))
#         general_layout.addWidget(self.acq_time_input)
#         general_layout.addWidget(QLabel("Filename:"))
#         general_layout.addWidget(self.filename_input)

#         general_box.setLayout(general_layout)
#         layout.addWidget(general_box)

#         # Scan Mode Toggle
#         mode_box = QGroupBox("Scan Mode")
#         mode_layout = QHBoxLayout()
#         self.mode_group = QButtonGroup()
#         self.map_btn = QRadioButton("Map")
#         self.line_btn = QRadioButton("Line Scan")
#         self.map_btn.setChecked(True)
#         self.mode_group.addButton(self.map_btn)
#         self.mode_group.addButton(self.line_btn)
#         mode_layout.addWidget(self.map_btn)
#         mode_layout.addWidget(self.line_btn)
#         mode_box.setLayout(mode_layout)
#         layout.addWidget(mode_box)

#         # Buttons
#         self.start_button = QPushButton("Start Scan")
#         self.cancel_button = QPushButton("Cancel Scan")
#         self.start_button.clicked.connect(self.start_scan)
#         self.cancel_button.clicked.connect(self.cancel_scan)
#         layout.addWidget(self.start_button)
#         layout.addWidget(self.cancel_button)

#         # Output log
#         self.log_box = QTextEdit()
#         self.log_box.setReadOnly(True)
#         layout.addWidget(QLabel("Status Log:"))
#         layout.addWidget(self.log_box)

#         self.setLayout(layout)

#     def start_scan(self):
#         mode = "map" if self.map_btn.isChecked() else "linescan"
#         self.log_box.append(f"Starting scan in mode: {mode}")
#         self.log_box.append(f"Acq time: {self.acq_time_input.text()} ms")
#         self.log_box.append(f"Filename: {self.filename_input.text()}")

#     def cancel_scan(self):
#         self.log_box.append("Scan cancelled.")

# if __name__ == '__main__':
#     app = QApplication(sys.argv)
#     gui = AcquisitionControlUI()
#     gui.show()
#     sys.exit(app.exec_())


import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QPlainTextEdit,
    QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal

# Import your existing AcquisitionControl and DummyMicroscope
# from their module (adjust the import path as needed):
# from acquisition_control import AcquisitionControl, DummyMicroscope

# For demonstration, a minimal DummyMicroscope and AcquisitionControl stub:

from acquisitioncontrol import AcquisitionControl
from simulation import DummyMicroscope


# Command line input with history
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

# Text console for stdout/stderr
class TextConsole(QPlainTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
    def write(self, text):
        self.appendPlainText(text)
    def flush(self):
        pass

class MainWindow(QMainWindow):
    def __init__(self, acq_ctrl):
        super().__init__()
        self.acq_ctrl = acq_ctrl
        self.setWindowTitle("Acquisition GUI")
        self.resize(1200, 800)
        self.param_entries = {}
        self.start_pos = [0,0,0]
        self.stop_pos = [0,0,0]
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        main_layout = QHBoxLayout(central)
        self.setCentralWidget(central)

        # Left: parameter tabs
        self.tabs = QTabWidget()
        self.build_param_tabs()
        main_layout.addWidget(self.tabs, 1)

        # Right: controls + console + plot
        right_layout = QVBoxLayout()

        # Stage Control
        stage_group = QGroupBox("Stage Control")
        sl = QHBoxLayout()
        btn_move_x = QPushButton("Move X")
        btn_move_y = QPushButton("Move Y")
        btn_set_start = QPushButton("Set Start")
        btn_set_stop = QPushButton("Set Stop")
        sl.addWidget(btn_move_x)
        sl.addWidget(btn_move_y)
        sl.addWidget(btn_set_start)
        sl.addWidget(btn_set_stop)
        stage_group.setLayout(sl)
        right_layout.addWidget(stage_group)

        # Position Display
        pos_group = QGroupBox("Positions / Estimate")
        pl = QVBoxLayout()
        self.label_start = QLabel("Start: (0.0, 0.0, 0.0)")
        self.label_stop = QLabel("Stop: (0.0, 0.0, 0.0)")
        self.label_est = QLabel("Estimated runtime: 0.0s")
        pl.addWidget(self.label_start)
        pl.addWidget(self.label_stop)
        pl.addWidget(self.label_est)
        pos_group.setLayout(pl)
        right_layout.addWidget(pos_group)

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

        # Redirect prints
        sys.stdout = self.console
        sys.stderr = self.console

        # Connect signals
        btn_set_start.clicked.connect(self.set_start)
        btn_set_stop.clicked.connect(self.set_stop)
        btn_move_x.clicked.connect(lambda: self.move_axis('x'))
        btn_move_y.clicked.connect(lambda: self.move_axis('y'))
        self.cmd_input.enter_pressed.connect(self.handle_command)

    def build_param_tabs(self):
        sections = {
            'General':    self.acq_ctrl.general_parameters,
            'Motion':     self.acq_ctrl.motion_parameters,
            'Wavelength': self.acq_ctrl.wavelength_parameters,
            'Polarization': self.acq_ctrl.polarization_parameters
        }
        for name, params in sections.items():
            tab = QWidget()
            vl = QVBoxLayout(tab)
            self.build_section(vl, params, name.lower())
            self.tabs.addTab(tab, name)

    def build_section(self, layout, param_dict, prefix):
        # nested or flat
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

    def set_stop(self):
        coords = self.acq_ctrl.current_stage_coordinates
        self.stop_pos = coords
        self.label_stop.setText(f"Stop: ({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})")
        self.update_estimate()

    def move_axis(self, axis):
        print(f"Moving axis {axis}")

    def handle_command(self, text):
        print(f">>> {text}")
        try:
            self.run_command(text)
        except Exception as e:
            print(f"Error: {e}")
        # self.cmd_input.clear()
        # raise NotImplementedError("Command handling not implemented yet.")

    def update_estimate(self):
        est = self.acq_ctrl.estimate_scan_duration()
        self.label_est.setText(f"Estimated runtime: {est:.1f}s")

def main():
    app = QApplication(sys.argv)
    acq = AcquisitionControl(microscope=DummyMicroscope())
    w = MainWindow(acq)
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

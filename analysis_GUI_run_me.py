import sys
import json
import copy
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QListWidget, QLabel, QMessageBox,
    QFileDialog, QListWidgetItem
)
from PyQt5.QtCore import Qt
from analysis_spectroscopy import DataSet  # Your module

class AnalysisGUI(QWidget):
    def __init__(self, dataset=None, dataDir=None):
        super().__init__()
        self.setWindowTitle("Analysis Workflow Builder")
        self.dataset = None
        self.dataDir = dataDir
        self.workflow = []
        self.checkpoints = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Function picker and argument input
        self.function_select = QComboBox()
        self.function_select.addItems([
            "initialise", "index_from_filenames", "_use_index_filenames", "sort_by_scan_index",
            "frames_to_spectrum", "subtract_background_files", "plot_current",
            "calibrate_excitation_wavelength", "baseline_all", "plot_2D_test",
            "save_database"
        ])

        self.arg_input = QLineEdit()
        self.arg_input.setPlaceholderText('Arguments as dict, e.g., {"offset": 1000}')

        add_btn = QPushButton("Add Step")
        add_btn.clicked.connect(self.add_step)

        self.step_list = QListWidget()
        self.step_list.setDragDropMode(QListWidget.InternalMove)

        run_btn = QPushButton("Run Workflow")
        run_btn.clicked.connect(self.run_workflow)

        rollback_btn = QPushButton("Rollback")
        rollback_btn.clicked.connect(self.rollback_checkpoint)

        save_btn = QPushButton("Save Database")
        save_btn.clicked.connect(self.save_data)

        export_btn = QPushButton("Export Workflow")
        export_btn.clicked.connect(self.export_workflow)

        import_btn = QPushButton("Import Workflow")
        import_btn.clicked.connect(self.import_workflow)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        layout.addWidget(QLabel("Select Function"))
        layout.addWidget(self.function_select)
        layout.addWidget(QLabel("Arguments"))
        layout.addWidget(self.arg_input)
        layout.addWidget(add_btn)
        layout.addWidget(self.step_list)

        button_layout = QHBoxLayout()
        button_layout.addWidget(run_btn)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(rollback_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(import_btn)

        layout.addLayout(button_layout)
        layout.addWidget(QLabel("Execution Log"))
        layout.addWidget(self.log_output)

        self.setLayout(layout)

    def add_step(self):
        func_name = self.function_select.currentText()
        args_text = self.arg_input.text()
        
        print(f"Adding step: {func_name} with args: {args_text}")
        try:
            args = json.loads(args_text) if args_text else {}
        except Exception as e:
            self.log_output.append(f"Error parsing arguments: {e}")
            return

        self.workflow.append((func_name, args))
        self.step_list.addItem(f"{func_name} {args}")

    def update_workflow_from_list(self):
        self.workflow = []
        for index in range(self.step_list.count()):
            item_text = self.step_list.item(index).text()
            func, _, arg_str = item_text.partition(" ")
            args = json.loads(arg_str) if arg_str else {}
            self.workflow.append((func, args))

    def run_workflow(self):
        self.update_workflow_from_list()
        if self.dataset is None:
            self.dataset = DataSet(self.dataDir, initialise=False)
            self.log_output.append("Created dataset")

        self.checkpoints.append(copy.deepcopy(self.dataset))
        for func_name, args in self.workflow:
            self.log_output.append(f"Running {func_name} with {args}")
            try:
                func = getattr(self.dataset, func_name)
                func(**args) if args else func()
            except Exception as e:
                self.log_output.append(f"Error: {e}")
                return

    def rollback_checkpoint(self):
        if len(self.checkpoints) > 1:
            self.checkpoints.pop()
            self.dataset = self.checkpoints[-1]
            self.log_output.append("Rolled back to last checkpoint")
        else:
            self.log_output.append("No checkpoints to rollback to")

    def save_data(self):
        if self.dataset:
            self.dataset.save_database()
            self.log_output.append("Saved database")

    def export_workflow(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Workflow", filter="JSON Files (*.json)")
        if not path:
            return
        self.update_workflow_from_list()
        try:
            with open(path, "w") as f:
                json.dump(self.workflow, f, indent=2)
            self.log_output.append(f"Exported workflow to {path}")
        except Exception as e:
            self.log_output.append(f"Export failed: {e}")

    def import_workflow(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Workflow", filter="JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as f:
                self.workflow = json.load(f)
            self.step_list.clear()
            for func_name, args in self.workflow:
                self.step_list.addItem(f"{func_name} {json.dumps(args)}")
            self.log_output.append(f"Imported workflow from {path}")
        except Exception as e:
            self.log_output.append(f"Import failed: {e}")

if __name__ == '__main__':
    dataDir = r'C:\Users\Sam\Data\14MayWLMoS2'
    app = QApplication(sys.argv)
    gui = AnalysisGUI(dataDir=dataDir)
    gui.resize(900, 600)
    gui.show()
    sys.exit(app.exec_())

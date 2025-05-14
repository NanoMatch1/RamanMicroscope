import dearpygui.dearpygui as dpg

scan_type = {"mode": "map"}

def toggle_mode_callback():
    scan_type["mode"] = "linescan" if scan_type["mode"] == "map" else "map"
    dpg.set_value("mode_button", f"Mode: {scan_type['mode'].capitalize()}")

def start_scan_callback():
    print("Starting scan...")
    print("Mode:", scan_type["mode"])
    print("Separate resolution:", dpg.get_value("separate_res_checkbox"))
    print("Z axis scan:", dpg.get_value("z_axis_checkbox"))

dpg.create_context()
dpg.create_viewport(title='Acquisition GUI', width=400, height=300)
dpg.setup_dearpygui()

with dpg.window(label="Acquisition GUI", width=390, height=280):
    dpg.add_input_text(label="Acquisition Time", default_value="1000", tag="acq_time")
    dpg.add_input_text(label="Filename", default_value="default", tag="filename")
    
    dpg.add_button(label="Mode: Map", callback=toggle_mode_callback, tag="mode_button")
    dpg.add_checkbox(label="Enable Separate Resolution", tag="separate_res_checkbox", default_value=True)
    dpg.add_checkbox(label="Enable Z Axis Scanning", tag="z_axis_checkbox", default_value=False)

    dpg.add_button(label="Start Scan", callback=start_scan_callback)
    dpg.add_button(label="Quit", callback=lambda: dpg.stop_dearpygui())

dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()

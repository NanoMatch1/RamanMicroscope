
import os
import sys

from ramanmicroscope.interface import Interface

def main(startup_commands=[], simulate=False):
    # Create your CLI-backed controller
    
    interface = Interface(simulate=simulate, com_port='COM10', debug_skip=[
        #'camera', 
        #'TRIAX'
        ])
    # Start the command line interface
    interface.run_batch(startup_commands)
    # interface.modify_handler('all', logging.INFO)
    interface.cli()

if __name__ == "__main__":
    # quick switch for testing
    if "Users\\Sam" in os.getcwd():
        simulate = True 
    elif sys.platform == 'linux':
        simulate = True
    else:
        simulate = False

    startup_commands = [
    ]
    main(startup_commands=startup_commands, simulate=simulate)
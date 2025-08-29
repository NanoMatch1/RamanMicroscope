# RamanMicroscope
Code for running the tunable excitation Raman microscope

# 1. General Code Structure
The entire system contains multiple hardware components, some commecrial and some custom made. The custom motors are all driven by the ArduinoMEGA controller, but are treated in some cases as individual modules in the code for efficient compartmentalisation and abstraction.

Each hardware element, and each software element, where possible adhers to the principles of encapsulation and single purpose. 

## 1.1. Heirarchical Structure
The software structure follows a heirarchy with an overarching interface to manage the intepretation of commands and subsequent passing of commands to hardware methods/functions.

The Microscope is the first instrument in the heirarchy, as it manages multiple hardware interfaces to achieve the level of abstraction required to behave like a full Raman microscope. The interface layer is responsible for managing the GUI and command structure, while the microscope orchestrates the actuation of commands to achieve the desired purpose.

Wherever possible, hardware interaction is handled at the lowest level, and wrapped by each hardware module to expose logical packaged methods to the user. The microscope ususally targets those logical methods wherever possible when directing the instrument.
For instance, the "Microscope.go_to_lambda_wavelength" function logically simple - go to wavelength <lambda> - but initiates a range of coordination over multiple components to move the laser motors, acquire a spectrum, measure the peak wavelength, then move the grating motors and restore the system to a ready state. The microscope must reach across multiple hardware components to achieve this, as well as communicate with the calibration service.
For the most part, the user only needs to know the top level microscope functions, which are presented to the help menu. For debugging and adding features, knowledge of the software structure of the all the hardware objects is required.

## 1.2. Hardware Object Structure
Each hardware object is designed to be a self-contained module which could operate independently of the greater microscope. The code should be self-contained, and reveal to the microscope only the high-level functions required to achieve the result of that hardware element. 
For instance, a new camera can be installed without rewriting the mircoscope code. The new camera has it's own class which wraps internal processes, exposing to the microscope only the commands it needs - such as "grab_frame", and "set_acquisition_time". 
Function decorators allow the interface layer to construct a command_map which maps input string commands to the hardware-class-level functions, so that the hardware can independently operate. This allows "laseron" to directly call Laser.laser_on() rather than going through the microscope. 
While this is useful for propotyping, in the production versions of the microscope, all high-level functions are eventually intended to be handled by the microscope, so that GUI integration is possible. As such, the command_map can be toggled between hardware-level functions and Microscope-level functions (Note: toggle currently not implemented as of v1.0) #TODO



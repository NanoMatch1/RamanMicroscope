import numpy as np

x_values = np.arange(0, 100, 1)
y_values = np.arange(100, 200, 1)
z_values = np.arange(200, 300, 1)

# position_sequence = 

import numpy as np
from itertools import product

def generate_raster_positions(bounds, resolutions, scan_axes=('X', 'Y'), fixed_values=None):
    """
    Generate a flattened list of [X, Y, Z] positions for a raster scan.

    Parameters:
        bounds (dict): Dict with axis keys ('X', 'Y', 'Z') and (min, max) tuples.
        resolutions (dict): Dict with axis keys and step sizes.
        scan_axes (tuple): Axes to scan over, in the order of fastest to slowest changing.
        fixed_values (dict): Dict with fixed axis values for non-scanning axes.

    Returns:
        positions (list of lists): Flattened list of [X, Y, Z] coordinates.
    """
    # Determine full axis order
    all_axes = ['X', 'Y', 'Z']
    fixed_values = fixed_values or {}

    # Build coordinate arrays for scan axes
    coords = {}
    for axis in scan_axes:
        start, end = bounds[axis]
        step = resolutions[axis]
        coords[axis] = np.arange(start, end + step/2, step)  # +step/2 for inclusive range

    # Create all combinations in the specified axis order
    mesh = list(product(*(coords[ax] for ax in scan_axes)))

    # Construct full [X, Y, Z] from mesh
    positions = []
    for point in mesh:
        pos = {axis: fixed_values.get(axis, None) for axis in all_axes}
        for i, axis in enumerate(scan_axes):
            pos[axis] = point[i]
        # Default fixed value is 0 if not provided
        final = [pos[axis] if pos[axis] is not None else 0.0 for axis in all_axes]
        positions.append(final)

    return positions

def raster_position_generator(bounds, resolutions, scan_axes=('X', 'Y'), fixed_values=None):
    """
    Generator that yields [X, Y, Z] positions one at a time.

    Parameters:
        bounds (dict): Axis keys with (min, max) tuples.
        resolutions (dict): Axis keys with step sizes.
        scan_axes (tuple): Axes that change, in order of fastest to slowest.
        fixed_values (dict): Axis keys with fixed values (for non-scanning axes).
    """
    all_axes = ['X', 'Y', 'Z']
    fixed_values = fixed_values or {}

    coords = {}
    for axis in scan_axes:
        start, end = bounds[axis]
        step = resolutions[axis]
        coords[axis] = np.arange(start, end + step/2, step)

    for point in product(*(coords[ax] for ax in scan_axes)):
        pos = {axis: fixed_values.get(axis, None) for axis in all_axes}
        for i, axis in enumerate(scan_axes):
            pos[axis] = point[i]
        yield [pos[axis] if pos[axis] is not None else 0.0 for axis in all_axes]

# rasterlist = generate_raster_positions(
gen = raster_position_generator(
    bounds={'X': (0, 100), 'Y': (100, 200), 'Z': (200, 300)},
    resolutions={'X': 1, 'Y': 1, 'Z': 1},
    scan_axes=('Y', 'X'),
    fixed_values={'Z': 0}
)

# print(rasterlist)
for pos in gen:
    print(pos)
breakpoint()
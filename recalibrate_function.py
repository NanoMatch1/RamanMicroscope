import numpy as np

def regenerate_polynomial_with_shift(coefficients, correction, num_points=100, domain=None, poly_order=None):
    """
    Shift polynomial output by subtracting a correction value, then re-fit to obtain new polynomial coefficients.

    Parameters:
        coefficients (list or array): Polynomial coefficients for the forward fit (e.g., wavelength → steps).
        correction (float): Value to subtract from each polynomial output (e.g., steps).
        num_points (int): Number of points to use in generating the synthetic data.
        domain (tuple): Optional (min, max) domain for the input axis. If None, uses (0, 1).
        poly_order (int): Optional polynomial order to fit. Defaults to original polynomial degree.

    Returns:
        dict: {
            'original': {'x': x, 'y': y, 'coeff': original_coefficients},
            'corrected': {
                'forward_coeff': new_forward_coeff,
                'inverse_coeff': new_inverse_coeff,
                'x': x,
                'y_corrected': y_corrected
            }
        }
    """
    poly = np.poly1d(coefficients)
    degree = poly_order if poly_order is not None else len(coefficients) - 1

    # Infer domain if not given
    if domain is None:
        domain = (0, 1)

    x = np.linspace(domain[0], domain[1], num_points)
    y = poly(x)
    y_corrected = y + correction

    # Fit new forward and inverse polynomials
    new_forward_coeff = np.polyfit(x, y_corrected, degree)
    new_inverse_coeff = np.polyfit(y_corrected, x, degree)

    return {
        'original': {
            'x': x,
            'y': y, 
            'coeff': coefficients
        },
        'corrected': {
            'x': x,
            'y_corrected': y_corrected,
            'forward_coeff': new_forward_coeff,
            'inverse_coeff': new_inverse_coeff
        }
    }


original_coeff = [0.10804683994803718, 331.8588098129754, 43950.89354704326] 
correction = -239041

result = regenerate_polynomial_with_shift(original_coeff, correction, domain=(650, 950), poly_order=2)

print("Old forward:", result['original']['coeff'])
print("New forward:", result['corrected']['forward_coeff'])
print("New inverse:", result['corrected']['inverse_coeff'])


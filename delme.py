def parse_input_data(data):
    """
    Accepts either:
      - A string such as 'x100 y200 z200', 'y21 z34', or 'y2 x5 z2'
      - A tuple of 3 floats
    Returns a dictionary mapping keys "X", "Y", "Z" to their respective float values.
    For string inputs, only keys present in the string are added.
    For tuple inputs, assumes order is (X, Y, Z).
    """
    # If data is a string
    if isinstance(data, str):
        result = {}
        # Split string by whitespace and iterate through each component
        for part in data.split():
            # The first character represents the key, which we capitalize
            # and the rest is the numeric part.
            if len(part) < 2:
                continue  # skip any malformed parts
            key = part[0].upper()
            try:
                value = float(part[1:])
                # Only add key if it is one of the expected options.
                if key in ['X', 'Y', 'Z']:
                    result[key] = value
            except ValueError:
                raise ValueError(f"Invalid numeric value in part: {part}")
        return result

    # If data is a tuple or list of length 3
    elif isinstance(data, (tuple, list)):
        if len(data) != 3:
            raise ValueError("Tuple input must have exactly three numeric values.")
        # Validate that each element is a float (or convertible to float)
        try:
            x, y, z = float(data[0]), float(data[1]), float(data[2])
        except ValueError:
            raise ValueError("All tuple elements must be numeric values.")
        return {"X": x, "Y": y, "Z": z}

    else:
        raise TypeError("Input must be either a string or a tuple/list of three floats.")


# Example Usage:
print(parse_input_data("x100 y200 z300"))  # {'X': 100.0, 'Y': 200.0, 'Z': 300.0}
print(parse_input_data("y21 z34"))         # {'Y': 21.0, 'Z': 34.0}
print(parse_input_data((5.5, 10.2)))   # {'X': 5.5, 'Y': 10.2, 'Z': 15.3}

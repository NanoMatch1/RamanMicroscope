import numpy as np
import sys
import os

def load_npz(file_path):
    try:
        with np.load(file_path, allow_pickle=True) as data:
            return data
    except Exception as e:
        print(f"Failed to read file: {e}")
        return 

    except Exception as e:
        print(f"Failed to read file: {e}")


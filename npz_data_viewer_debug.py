import numpy as np
import sys
import os

def inspect_npz(file_path):
    try:
        with np.load(file_path, allow_pickle=True) as data:
            breakpoint()
            print(f"Contents of '{file_path}':")
            for key in data.files:
                arr = data[key]
                print(f"\nKey: {key}")
                print(f"Type: {type(arr)}, Shape: {arr.shape}, Dtype: {arr.dtype}")
                if arr.ndim == 0:
                    print(f"Value: {arr.item()}")
                elif arr.size < 10:
                    print(f"Values: {arr}")
                else:
                    print(f"Values (first few): {arr.flat[:5]} ...")

    except Exception as e:
        print(f"Failed to read file: {e}")

if __name__ == "__main__":
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    dataDir = os.path.join(scriptdir, "data")
    dataDir = r'C:\Users\Sam\matchbook\ramanproject\RamanMicroscope\data\scan_test_19'
    # if len(sys.argv) != 2:
    #     print("Usage: python inspect_npz.py <file_path>")
    # else:
    #     inspect_npz(dataDir)

    files = sorted([x for x in os.listdir(dataDir) if x.endswith(".npz")])
    files = [os.path.join(dataDir, x) for x in files]



    for file in files:
        inspect_npz(file)

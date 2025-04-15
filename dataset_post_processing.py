import glob
import h5py
import numpy as np
import os
import json

def bin_and_export_dataset(npz_dir, output_h5, binning_roi):
    spectra = []
    wavelengths = []
    metadata_list = []

    files = sorted(glob.glob(os.path.join(npz_dir, "*.npz")))

    for path in files:
        with np.load(path) as npz:
            img = npz['image']
            wl = npz['wavelength']
            md = json.loads(npz['metadata'].item())

        # Bin spectrum
        y0, y1 = binning_roi
        y0 = max(0, min(img.shape[0], y0))
        y1 = max(0, min(img.shape[0], y1))
        spec = np.mean(img[y0:y1, :], axis=0)

        spectra.append(spec)
        wavelengths.append(wl)
        metadata_list.append(md)

    # Dump to HDF5
    spectra = np.stack(spectra).astype(np.float32)
    wavelengths = np.stack(wavelengths).astype(np.float32)

    with h5py.File(output_h5, 'w') as f:
        f.create_dataset("spectra", data=spectra, compression="gzip")
        f.create_dataset("wavelengths", data=wavelengths, compression="gzip")

        meta_group = f.create_group("metadata")
        for key in metadata_list[0]:
            values = [str(md[key]) for md in metadata_list]
            meta_group.create_dataset(key, data=np.array(values, dtype=h5py.string_dtype()))

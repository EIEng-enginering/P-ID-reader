"""Read .npy files from untrusted sources without ever executing code.

numpy.load(allow_pickle=True) can run arbitrary code from a pickled object array. This reader refuses pickle unless the pickle only reconstructs
numpy arrays/scalars/dtypes and plain builtin containers: every other global (os.system, subprocess, builtins.eval, ...) raises UnpicklingError.
Files over MAX_BYTES are refused (pickle memory blow-up). Plain numeric .npy files are read with allow_pickle=False.
"""
import io
import pickle

import numpy as np

MAX_BYTES = 64 * 1024 * 1024
_ALLOWED = {
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
    ("builtins", "list"), ("builtins", "tuple"), ("builtins", "dict"), ("builtins", "set"), ("builtins", "frozenset"),
    ("builtins", "str"), ("builtins", "int"), ("builtins", "float"), ("builtins", "bool"), ("builtins", "bytes"), ("builtins", "complex"), ("builtins", "slice"),
    ("collections", "OrderedDict"),
}


class RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in _ALLOWED:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"refused global {module}.{name}")


def header(data):
    """(dtype, shape, fortran_order, offset) from the .npy header text only (no data parsing)."""
    f = io.BytesIO(data)
    version = np.lib.format.read_magic(f)
    reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
    shape, fortran, dtype = reader(f)
    return dtype, shape, fortran, f.tell()


def load(path):
    with open(path, "rb") as fh:
        data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("file too large for the safe reader")
    dtype, shape, fortran, offset = header(data)
    if not dtype.hasobject:
        return np.load(io.BytesIO(data), allow_pickle=False)
    return RestrictedUnpickler(io.BytesIO(data[offset:])).load()

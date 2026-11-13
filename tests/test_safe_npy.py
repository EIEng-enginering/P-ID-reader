"""safe_npy: object arrays load only when the pickle is plain numpy/containers; anything that could run code is refused."""
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "data"))
import safe_npy  # noqa: E402


def write_object_npy(path, obj):
    arr = np.empty(len(obj), dtype=object)
    for i, v in enumerate(obj):
        arr[i] = v
    np.save(path, arr, allow_pickle=True)


def test_plain_numeric_file_loads_without_pickle(tmp_path):
    p = tmp_path / "a.npy"
    np.save(p, np.arange(6).reshape(2, 3))
    assert safe_npy.load(p).tolist() == [[0, 1, 2], [3, 4, 5]]


def test_object_array_of_plain_data_loads(tmp_path):
    p = tmp_path / "o.npy"
    write_object_npy(p, [["PIT-123", [1, 2, 3, 4]], ["FY-1", [5, 6, 7, 8]]])
    out = safe_npy.load(p)
    assert out[0][0] == "PIT-123" and list(out[1][1]) == [5, 6, 7, 8]


class Evil:
    def __reduce__(self):
        return (os.system, ("echo pwned > " + str(Path(os.getcwd()) / "SHOULD_NOT_EXIST.txt"),))


def test_a_code_executing_pickle_is_refused_and_does_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "evil.npy"
    write_object_npy(p, [Evil()])
    with pytest.raises(pickle.UnpicklingError, match="refused global"):
        safe_npy.load(p)
    assert not (tmp_path / "SHOULD_NOT_EXIST.txt").exists()


def test_oversized_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(safe_npy, "MAX_BYTES", 100)
    p = tmp_path / "big.npy"
    np.save(p, np.arange(1000))
    with pytest.raises(ValueError):
        safe_npy.load(p)

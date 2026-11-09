"""Save every imported drawing as its own set of files, named after the original P&ID file.

For a drawing ``NAME.pdf`` the chosen folder receives:

* ``NAME.json``        full readings report (readings, sheet info, loops, checks, layers, OCR words)
* ``NAME.html``        printable report with annotated drawing images
* ``NAME.graph.json``  proposed connectivity graph (canonical JSON)
* ``NAME.graphml``     the same graph as GraphML

A multi-page PDF is one set of files with every page inside. Nothing is overwritten: when any of the
files already exists the whole set is saved as ``NAME (2)``, ``NAME (3)`` and so on.
Everything written is an unverified proposal from the drawing, not an engineering approval.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from typing import Callable

from ..api import canonical_json
from .graph_export import canonical_graph, to_graphml
from .reports import encode_report, make_report

SUFFIXES = (".json", ".html", ".graph.json", ".graphml")
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_stem(filename: str) -> str:
    """Original file name without its .pdf extension, made safe as a Windows file name."""
    name = Path(str(filename).replace("\\", "/")).name
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    stem = _BAD.sub("_", stem).strip(" .") or "drawing"
    if stem.split(".")[0].upper() in _RESERVED:
        stem = "_" + stem
    return stem[:150]


def unique_stem(folder: Path, stem: str) -> str:
    """First of NAME, NAME (2), NAME (3)… for which none of the output files exists yet."""
    n = 1
    while True:
        candidate = stem if n == 1 else f"{stem} ({n})"
        if not any((folder / (candidate + s)).exists() for s in SUFFIXES):
            return candidate
        n += 1


def _write_new(path: Path, payload: bytes) -> None:
    """Write a complete file or nothing; never replace an existing file."""
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".pid-export-", suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            raise
        except OSError:
            os.rename(temp, path)  # filesystem without hard links; rename still refuses to replace on Windows
            temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def export_drawing(store, extraction_id: str, folder: str | Path) -> list[Path]:
    """Write the file set for one imported drawing. Returns the paths written."""
    out = Path(folder)
    if not out.is_dir():
        raise FileNotFoundError("The chosen folder does not exist")
    filename = store.export_extraction(extraction_id)["document"]["filename"]
    report = make_report(store, extraction_ids=[extraction_id], include_images=True)
    graph = canonical_graph(store, extraction_id)
    payloads = {
        ".json": encode_report(report, "json"),
        ".html": encode_report(report, "html"),
        ".graph.json": (canonical_json(graph) + "\n").encode("utf-8"),
        ".graphml": to_graphml(graph).encode("utf-8"),
    }
    stem = unique_stem(out, safe_stem(filename))
    written: list[Path] = []
    try:
        for suffix in SUFFIXES:
            target = out / (stem + suffix)
            _write_new(target, payloads[suffix])
            written.append(target)
    except Exception:
        for p in written:  # never leave a half set behind
            p.unlink(missing_ok=True)
        raise
    return written


def export_drawings(store, extraction_ids: list[str] | None, folder: str | Path,
                    progress: Callable[[int, int, str], None] | None = None,
                    should_stop: Callable[[], bool] | None = None) -> dict:
    """Export several drawings; one failing drawing does not stop the others.

    ``extraction_ids=None`` means every drawing in the project. Returns
    ``{"folder", "saved": [(drawing, [paths])], "failed": [(drawing, reason)]}``.
    """
    if extraction_ids is None:
        extraction_ids = [r[0] for r in store.db.execute(
            "SELECT extraction_id FROM extraction ORDER BY imported_utc, extraction_id")]
    if not extraction_ids:
        raise ValueError("No drawings in the project")
    saved, failed = [], []
    for i, eid in enumerate(extraction_ids, 1):
        if should_stop and should_stop():
            break  # files already saved stay; each drawing's set is complete or absent
        try:
            name = store.export_extraction(eid)["document"]["filename"]
        except Exception as exc:
            failed.append((eid, f"{type(exc).__name__}: {exc}"))
            continue
        if progress:
            progress(i, len(extraction_ids), name)
        try:
            saved.append((name, export_drawing(store, eid, folder)))
        except Exception as exc:
            failed.append((name, f"{type(exc).__name__}: {exc}"))
    return {"folder": str(folder), "saved": saved, "failed": failed}

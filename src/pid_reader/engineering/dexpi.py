"""DEXPI exchange adapter - deliberately DISABLED.

A DEXPI (Proteus XML) export is only worth shipping if it validates against the
published DEXPI schema and carries correct piping/equipment semantics. This
project cannot yet establish either: drawn-line connectivity here is a set of
unverified proposals (no nozzles, flow direction, line classes or equipment
attributes), and no DEXPI validator has been run. Writing a file that merely
*looks* like DEXPI would invite engineers to trust it, so this adapter refuses.

Status: NOT_IMPLEMENTED. See docs/WIN_R01_STATUS.md for what is needed.
"""
from __future__ import annotations

STATUS = "NOT_IMPLEMENTED"
REASON = ("DEXPI export is disabled: reviewed, typed connectivity (nozzles, line classes, flow direction) and a "
          "schema/semantic validator run are prerequisites and are not available. Use the JSON/CSV/HTML "
          "reports, which state plainly that they are unverified drawing readings.")


class DexpiNotAvailable(NotImplementedError):
    pass


def export_dexpi(*_args, **_kwargs):
    raise DexpiNotAvailable(REASON)

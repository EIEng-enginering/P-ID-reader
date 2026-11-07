"""Shared dispatcher for the frozen executables (GUI exe and console exe).

Child-process flags are honoured by *both* executables so isolated readers work
no matter which one started them.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None, *, default: str = "gui") -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--pid-worker":
        from .worker import main as worker_main
        return worker_main(args[1:])
    if args and args[0] == "--pid-worker-standalone":
        from .engineering.standalone_worker import main as standalone_main
        return standalone_main(args[1:])
    if args and args[0] == "cli":
        args, default = args[1:], "cli"
    if default == "cli":
        from .cli import main as cli_main
        return cli_main(args)
    from .ui.app import run_app
    return run_app(args[0] if args else None)

"""Frozen GUI entry (PIDReader.exe): app, or child-process flags, or ``cli ...``."""
import sys
from pid_reader.entry import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], default="gui"))

"""Frozen console entry (pid-reader-cli.exe)."""
import sys
from pid_reader.entry import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], default="cli"))

"""Command-line entry point; run `python cli.py --help`."""
import multiprocessing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from experiment_planner.cli import main
    raise SystemExit(main())

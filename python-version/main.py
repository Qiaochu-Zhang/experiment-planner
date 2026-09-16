"""Run this file in PyCharm with a Python 3.12 interpreter."""
import multiprocessing
from pathlib import Path
import sys

# Use this folder's source even when another edition is installed. Resolve paths
# from this file so PyCharm's working-directory setting does not affect imports.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from experiment_planner.__main__ import main
    raise SystemExit(main())

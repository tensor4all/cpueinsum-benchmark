#!/usr/bin/env python3
"""Write the site under `result-v2/cpueinsum/` (landing page, history, HTML pages and the charts
the descriptor declares); see `campaign_toolkit.site`. Args pass through."""
import pathlib
import sys

from campaign_toolkit import site

ROOT = pathlib.Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    sys.exit(site.main(["--root", str(ROOT), *sys.argv[1:]]))

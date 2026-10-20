#!/usr/bin/env python3
"""Write `result/index.html`; see `campaign_toolkit.site`. Args pass through."""
import pathlib
import sys

from campaign_toolkit import site

ROOT = pathlib.Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    sys.exit(site.main(["--root", str(ROOT), *sys.argv[1:]]))

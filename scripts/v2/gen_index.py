#!/usr/bin/env python3
"""Shim: the logic lives in campaign_toolkit.gen_index.

Kept at this path, with the same CLI, so the campaign's docs, CI and habits do not
change when the shared tooling is updated. It lives under `scripts/v2/` because it
drives the timing-v2 contract this campaign records under, and because the tree it
writes (`data/v2-results/`, `result-v2/`) is the v2 tree.
"""
import pathlib
import sys

from campaign_toolkit.gen_index import main

if __name__ == "__main__":
    sys.exit(main(root=pathlib.Path(__file__).resolve().parents[2]))

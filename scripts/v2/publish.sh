#!/bin/sh
# One publication of cpueinsum: the two engine rows at the pin, then the site.
set -eu
taskset -c 0-3,12-15 python3 scripts/v2/record_run.py zen5-cpu cpueinsum
python3 scripts/v2/gen_site.py

#!/bin/sh
# One publication of cpueinsum: one suite per contraction order, then the site.
#
# The strategies are separate suites because their rows are not two implementations: each row is
# the measured library executing one declared order, and a table that put the two orders side by
# side invited the difference between them to be read as a comparison between implementations. A
# suite carries one row and is verified against the OMEinsum arm's diagnostics (the suite's own
# verify_args), which is an independent implementation rather than the other order of the same one.
set -eu
taskset -c 0-3,12-15 python3 scripts/v2/record_run.py zen5-cpu einsum-opt_size
taskset -c 0-3,12-15 python3 scripts/v2/record_run.py zen5-cpu einsum-opt_flops

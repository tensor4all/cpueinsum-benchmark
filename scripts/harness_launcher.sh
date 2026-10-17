#!/usr/bin/env bash
# The harness entry point `campaign_toolkit.record_run` executes for this campaign.
#
#   cpueinsum-bench run|verify ...   the built harness, with --instances <corpus>
#   cpueinsum-bench info ...         the built harness, plus the built artifact's
#                                    path and SHA-256 as extra key=value lines
#
# Why this file exists
# --------------------
# The recorder drives a harness through one fixed command line
# (`campaign_toolkit/record_run.py`: the verify pass at lines 691-701 and the timing
# pass at lines 716-729) built from the descriptor's `--threads/--n/--batch/--dtype/
# --family/--rows` and the suite's populations. It has no field for a harness input
# path. This harness needs one: `crates/cpueinsum-bench/src/main.rs` lines 263-266
# refuse a run with `--instances DIR is required`, because its corpus is not compiled
# in - it is the external `tenferro-einsum-benchmark` instance set.
#
# The campaign therefore owns the binding between the pinned harness and the pinned
# corpus. `scripts/build_for_cpueinsum_rev.sh` installs this file, unchanged, as
# `BIN_DIR/cpueinsum-bench` next to the cargo artifact, and the descriptor's
# `measured.binary` names it. So the bytes the recorder executes and hashes are a
# committed, reviewable file, and the artifact they dispatch to is stated below.
#
# `info` is passed through unchanged (it takes no corpus) so the recorder's identity
# readback still sees the harness's own output; the two extra lines name the artifact
# this entry point dispatches to, because the manifest's `binary.sha256` is this
# launcher's hash, not the artifact's.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
harness="$here/../release/cpueinsum-bench"

# The campaign root: the directory that owns `benchmarks/campaign.yaml`.
root="$here"
while [[ ! -f "$root/benchmarks/campaign.yaml" ]]; do
    parent="$(dirname "$root")"
    if [[ "$parent" == "$root" ]]; then
        echo "cpueinsum-bench: no benchmarks/campaign.yaml above $here" >&2
        exit 2
    fi
    root="$parent"
done
instances="$root/extern/tenferro-einsum-benchmark/data/instances"

command="${1:-}"
[[ -n "$command" ]] && shift

case "$command" in
    run|verify)
        [[ -d "$instances" ]] || {
            echo "cpueinsum-bench: $instances is missing; run $root/scripts/setup_extern_deps.sh" >&2
            exit 2
        }
        exec "$harness" "$command" --instances "$instances" "$@"
        ;;
    info)
        "$harness" info "$@"
        printf 'harness_artifact=%s\n' "$harness"
        printf 'harness_artifact_sha256=%s\n' "$(sha256sum "$harness" | cut -d' ' -f1)"
        ;;
    *)
        exec "$harness" "$command" "$@"
        ;;
esac

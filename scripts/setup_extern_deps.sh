#!/usr/bin/env bash
# Materialise the two external checkouts this campaign builds and measures against.
#
#   setup_extern_deps.sh                 # clone both, at the pinned revisions
#   setup_extern_deps.sh --measured DIR  # symlink an existing cpueinsum-rs checkout
#   setup_extern_deps.sh --corpus DIR    # symlink an existing corpus checkout
#
#   extern/cpueinsum-rs                <- pins/cpueinsum-rs.rev
#       the measured library and the harness it carries (`crates/cpueinsum-bench`)
#   extern/tenferro-einsum-benchmark   <- pins/tenferro-einsum-benchmark.rev
#       the einsum instance corpus (`data/instances/*.json`) the harness reads
#
# Both are inputs, not copies: nothing here is committed, and the revision each run
# measured against is recorded in its own `run.yaml`.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

materialise() {
    local link="$1" url="$2" pin="$3" marker="$4" label="$5"
    local rev
    rev="$(sed -n 's/^[[:space:]]*\([0-9a-f]\{7,\}\)[[:space:]]*$/\1/p' "$pin" | tail -1)"
    [[ -n "$rev" ]] || { echo "ERROR: $pin names no revision" >&2; exit 1; }
    if [[ -d "$link/.git" ]]; then
        git -C "$link" fetch -q origin
    else
        rm -rf "$link"
        git clone -q "$url" "$link"
    fi
    git -C "$link" checkout -q "$rev"
    [[ -e "$link/$marker" ]] || {
        echo "ERROR: $link is not a $label checkout ($marker is missing)" >&2; exit 1; }
    echo "$label at $rev ($(git -C "$link" log --oneline -1))"
}

symlink_checkout() {
    local link="$1" dir="$2" marker="$3" label="$4"
    dir="$(cd "$dir" && pwd -P)"
    [[ -e "$dir/$marker" ]] || {
        echo "ERROR: $dir is not a $label checkout ($marker is missing)" >&2; exit 1; }
    rm -rf "$link"
    ln -sfn "$dir" "$link"
    echo "$label -> $dir ($(git -C "$dir" rev-parse --short HEAD), dirty=$(
        [[ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]] && echo true || echo false))"
}

MEASURED_DIR=""; CORPUS_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --measured) MEASURED_DIR="${2:?--measured needs a directory}"; shift 2 ;;
        --corpus) CORPUS_DIR="${2:?--corpus needs a directory}"; shift 2 ;;
        *) echo "ERROR: unknown argument $1" >&2; exit 2 ;;
    esac
done

if [[ -n "$MEASURED_DIR" ]]; then
    symlink_checkout "$PROJECT_DIR/extern/cpueinsum-rs" "$MEASURED_DIR" \
        crates/cpueinsum-bench cpueinsum-rs
else
    materialise "$PROJECT_DIR/extern/cpueinsum-rs" \
        https://github.com/tensor4all/cpueinsum-rs "$PROJECT_DIR/pins/cpueinsum-rs.rev" \
        crates/cpueinsum-bench cpueinsum-rs
fi

if [[ -n "$CORPUS_DIR" ]]; then
    symlink_checkout "$PROJECT_DIR/extern/tenferro-einsum-benchmark" "$CORPUS_DIR" \
        data/instances tenferro-einsum-benchmark
else
    materialise "$PROJECT_DIR/extern/tenferro-einsum-benchmark" \
        https://github.com/tensor4all/tenferro-einsum-benchmark \
        "$PROJECT_DIR/pins/tenferro-einsum-benchmark.rev" \
        data/instances tenferro-einsum-benchmark
fi

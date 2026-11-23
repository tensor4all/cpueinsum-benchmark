#!/usr/bin/env bash
# Materialise the external checkouts this campaign builds and measures against.
#
#   setup_extern_deps.sh                         # clone all four, at the pinned revisions
#   setup_extern_deps.sh --measured DIR          # symlink an existing cpueinsum-rs checkout
#   setup_extern_deps.sh --corpus DIR            # symlink an existing corpus checkout
#   setup_extern_deps.sh --measured-grouped DIR  # symlink a cpueinsum-rs checkout for the route campaign
#   setup_extern_deps.sh --gemm-trace DIR        # symlink a symtn-rs checkout carrying the GEMM corpus
#
#   extern/cpueinsum-rs                <- pins/cpueinsum-rs.rev
#       the measured library and the harness it carries (`crates/cpueinsum-bench`)
#   extern/tenferro-einsum-benchmark   <- pins/tenferro-einsum-benchmark.rev
#       the einsum instance corpus (`data/instances/*.json`) the harness reads
#   extern/cpueinsum-rs-grouped        <- pins/cpueinsum-rs-grouped.rev
#       the same library at the grouped-GEMM route campaign's own pin, with its replay
#       harness (`crates/cpueinsum-replay`)
#   extern/symtn-gemm-trace            <- pins/symtn-gemm-trace.rev
#       symtn's grouped-GEMM capture corpus (`gemm-trace-corpus/*.jsonl.gz`), sparse
#
# All are inputs, not copies: nothing here is committed, and the revision each run
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

# The GEMM corpus carries its own digest table (`gemm-trace-corpus/README.md`, one row per file
# with its SHA-256). Every capture the harness can read must be in it with that digest: a
# capture regenerated on another host, or edited, is a different corpus.
check_trace_digests() {
    local dir="$1/gemm-trace-corpus" f want got n=0
    for f in "$dir"/*.jsonl.gz; do
        [[ -e "$f" ]] || { echo "ERROR: $dir holds no capture" >&2; exit 1; }
        want="$(sed -n "s/^| \`$(basename "$f")\` |.*| \`\([0-9a-f]\{64\}\)\` |$/\1/p" "$dir/README.md")"
        if command -v sha256sum >/dev/null; then got="$(sha256sum "$f" | cut -c1-64)"
        else got="$(shasum -a 256 "$f" | cut -c1-64)"; fi
        [[ -n "$want" && "$want" == "$got" ]] || {
            echo "ERROR: $f has sha256 $got; the corpus README lists ${want:-no digest} for it" >&2; exit 1; }
        n=$((n + 1))
    done
    echo "symtn-gemm-trace: $n capture(s), every digest matches the corpus README"
}

MEASURED_DIR=""; CORPUS_DIR=""; GROUPED_DIR=""; TRACE_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --measured) MEASURED_DIR="${2:?--measured needs a directory}"; shift 2 ;;
        --corpus) CORPUS_DIR="${2:?--corpus needs a directory}"; shift 2 ;;
        --measured-grouped) GROUPED_DIR="${2:?--measured-grouped needs a directory}"; shift 2 ;;
        --gemm-trace) TRACE_DIR="${2:?--gemm-trace needs a directory}"; shift 2 ;;
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

if [[ -n "$GROUPED_DIR" ]]; then
    symlink_checkout "$PROJECT_DIR/extern/cpueinsum-rs-grouped" "$GROUPED_DIR" \
        crates/cpueinsum-replay cpueinsum-rs
else
    materialise "$PROJECT_DIR/extern/cpueinsum-rs-grouped" \
        https://github.com/tensor4all/cpueinsum-rs "$PROJECT_DIR/pins/cpueinsum-rs-grouped.rev" \
        crates/cpueinsum-replay cpueinsum-rs
fi

# The route campaign needs the vendor GEMM to run inside the caller's team, which cpueinsum-rs
# does from 1ca7431 on; before it, a `blas` row above one thread measures one CPU.
git -C "$PROJECT_DIR/extern/cpueinsum-rs-grouped" merge-base --is-ancestor \
    1ca74312aa7d32b7ec189e191e39db11fcd331c7 HEAD || {
    echo "ERROR: pins/cpueinsum-rs-grouped.rev predates cpueinsum-rs 1ca7431 (vendor GEMM in the caller's team)" >&2
    exit 1; }

if [[ -n "$TRACE_DIR" ]]; then
    symlink_checkout "$PROJECT_DIR/extern/symtn-gemm-trace" "$TRACE_DIR" \
        gemm-trace-corpus/README.md symtn-rs
else
    # Only the corpus directory is checked out: the rest of symtn is not an input here.
    link="$PROJECT_DIR/extern/symtn-gemm-trace"
    if [[ ! -d "$link/.git" ]]; then
        rm -rf "$link"
        git clone -q --filter=blob:none --sparse https://github.com/Ryo-wtnb11/symtn-rs "$link"
        git -C "$link" sparse-checkout set gemm-trace-corpus
    fi
    materialise "$link" https://github.com/Ryo-wtnb11/symtn-rs "$PROJECT_DIR/pins/symtn-gemm-trace.rev" \
        gemm-trace-corpus/README.md symtn-rs
fi
check_trace_digests "$PROJECT_DIR/extern/symtn-gemm-trace"

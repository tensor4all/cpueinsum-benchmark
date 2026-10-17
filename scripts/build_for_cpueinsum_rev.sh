#!/usr/bin/env bash
# Build the campaign harness out of one cpueinsum-rs checkout, into a target directory
# keyed by that checkout's commit.
#
#   build_for_cpueinsum_rev.sh <cpueinsum-rs-dir> <out-var-file> [bin...]
#
# Writes shell assignments to <out-var-file>:
#   CPUEINSUM_REV, CPUEINSUM_DIRTY, CPUEINSUM_DIR, BUILD_FEATURES, BIN_DIR
#
# Three things this deliberately does *not* do.
#
# It does not build the harness from this repository. `crates/cpueinsum-bench` is part
# of cpueinsum-rs and is compiled out of the same checkout as the library it measures,
# so `run.yaml`'s commit describes both. A harness built elsewhere could silently
# measure a different revision of the library than the one it was written against.
#
# It does not let two revisions share a target directory, and it clears the compiler
# cache for the build: a cache keyed on inputs that do not include the checkout can mix
# revisions, which is how a binary that did not contain the change under test once
# reached a measurement.
#
# It does not guess what the harness should measure against. The harness needs the
# instance corpus on its command line (`crates/cpueinsum-bench/src/main.rs:263-266`) and
# the recorder's harness command line is fixed and has no field for it, so `BIN_DIR`
# holds `scripts/harness_launcher.sh` installed as `measured.binary`, bound to the
# corpus checkout `scripts/setup_extern_deps.sh` materialises. The cargo artifact stays
# where cargo put it; the launcher is what dispatches to it.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CPUEINSUM_DIR="$(cd "${1:?cpueinsum-rs checkout required}" && pwd -P)"
OUT_FILE="${2:?output variable file required}"
shift 2
BINS=("$@")
[[ ${#BINS[@]} -gt 0 ]] || BINS=(cpueinsum-bench)

[[ -d "$CPUEINSUM_DIR/crates/cpueinsum-bench" ]] || {
    echo "ERROR: $CPUEINSUM_DIR is not a cpueinsum-rs checkout with the harness" >&2; exit 1; }
MANIFEST="$CPUEINSUM_DIR/Cargo.toml"
[[ -f "$MANIFEST" ]] || { echo "ERROR: $MANIFEST not found" >&2; exit 1; }

rev="$(git -C "$CPUEINSUM_DIR" rev-parse HEAD)"
dirty=false
[[ -z "$(git -C "$CPUEINSUM_DIR" status --porcelain --untracked-files=no)" ]] || dirty=true
suffix=""; [[ $dirty == true ]] && suffix="-dirty"
target="$PROJECT_DIR/target/cpueinsum-rev/${rev:0:12}${suffix}"
profile="${BENCH_BUILD_PROFILE:-release}"

bin_args=(); for bin in "${BINS[@]}"; do bin_args+=(--bin "$bin"); done
profile_flag=(); subdir=debug
if [[ "$profile" == release ]]; then profile_flag=(--release); subdir=release; fi

FEATURES="${BENCH_FEATURES:-}"
# An empty feature list must not become `--features ""`, which cargo rejects.
feature_flag=(); [[ -n "$FEATURES" ]] && feature_flag=(--features "$FEATURES")
RUSTC_WRAPPER= CARGO_TARGET_DIR="$target" cargo build --manifest-path "$MANIFEST" \
    "${profile_flag[@]}" "${feature_flag[@]}" "${bin_args[@]}" >&2

artifact="$target/$subdir/cpueinsum-bench"
[[ -x "$artifact" ]] || { echo "ERROR: $artifact was not built" >&2; exit 1; }

# The entry point the recorder executes, and the revision it is keyed to. Installed
# verbatim, so the hash the manifest records is the committed launcher's, not a
# generated file's.
bin_dir="$target/bin"
mkdir -p "$bin_dir"
install -m 755 "$PROJECT_DIR/scripts/harness_launcher.sh" "$bin_dir/cpueinsum-bench"

{
    printf 'CPUEINSUM_REV=%q\n' "$rev"
    printf 'CPUEINSUM_DIRTY=%q\n' "$dirty"
    printf 'CPUEINSUM_DIR=%q\n' "$CPUEINSUM_DIR"
    printf 'BIN_DIR=%q\n' "$bin_dir"
    # Not `%q`: a feature list is identifiers and commas, and quoting it would put a
    # backslash in front of every comma the manifest has to split on.
    printf 'BUILD_FEATURES=%s\n' "$FEATURES"
} > "$OUT_FILE"
echo "built ${BINS[*]} for cpueinsum-rs $rev (dirty=$dirty); harness artifact $artifact; entry point $bin_dir/cpueinsum-bench" >&2

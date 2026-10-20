#!/bin/sh
# The Julia arm behind the harness CLI contract, so the campaign recorder can drive it.
#
# The recorder knows one thing: a binary with `info`, `verify` and `run`, whose `run --csv` writes the
# timing schema and whose `verify` checks the numbers. Making the Julia arm speak that contract keeps
# everything the recorder does - the pinning, the idle guard, the process sets, the rotation, the CSV
# schema - and means the arm is not a second measurement mechanism that has to be trusted separately.
#
# The real work is `einsum_runner.jl` next to this file; this translates arguments.
#
#   harness.sh info [--threads N]
#   harness.sh verify --threads N --rows A[,B] --regime R --csv PATH [--diagnostics-csv PATH] ...
#   harness.sh run    --threads N --rows A[,B] --regime R --csv PATH [--reps M --prime-ms MS] ...
#
# `--rows` names the corpus's contraction orders (`opt_size`, `opt_flops`), which is what the
# campaign's strategy axis is here: each is a separate execution of the same instance.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
project="$here"
runner="$here/einsum_runner.jl"

# The measured checkout and the corpus are supplied by the descriptor; the recorder appends them to
# every verify/run invocation as `--instances DIR`.
instances=""
command=""
threads=1
rows="opt_size"
regime="cpueinsum"
csv=""
diagnostics_csv=""
reps=5
prime_ms=250

if [ $# -eq 0 ]; then
    echo "usage: harness.sh info|verify|run [flags]" >&2
    exit 2
fi
command=$1
shift

while [ $# -gt 0 ]; do
    case "$1" in
        --threads) threads=$2; shift 2 ;;
        --rows) rows=$2; shift 2 ;;
        --regime) regime=$2; shift 2 ;;
        --csv) csv=$2; shift 2 ;;
        --diagnostics-csv) diagnostics_csv=$2; shift 2 ;;
        --reps) reps=$2; shift 2 ;;
        --prime-ms) prime_ms=$2; shift 2 ;;
        --instances) instances=$2; shift 2 ;;
        # Declared by the campaign but meaningless here: the corpus fixes its own extents.
        --n|--batch|--dtype|--family|--size|--engines|--rotate-rows|--statistic|--census-csv|--reference-csv)
            shift 2 ;;
        *) echo "harness.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

case "$command" in
    info)
        version=$(julia --project="$project" -e 'using OMEinsum; print(pkgversion(OMEinsum))')
        echo "harness=omeinsum-jl"
        echo "provider=omeinsum"
        echo "provider_version=$version"
        echo "threads=$threads"
        ;;
    verify|run)
        [ -n "$csv" ] || { echo "harness.sh: $command needs --csv PATH" >&2; exit 2; }
        first=1
        diag_tmp=""
        for row in $(echo "$rows" | tr ',' ' '); do
            tmp=$(mktemp)
            if [ -n "$diagnostics_csv" ]; then
                diag_tmp=$(mktemp)
                JULIA_NUM_THREADS="$threads" julia --project="$project" "$runner" \
                    --instances "$instances" --strategy "$row" --threads "$threads" \
                    --reps "$reps" --prime-ms "$prime_ms" --regime "$regime" \
                    --csv "$tmp" --diagnostics-csv "$diag_tmp" >&2
            else
                JULIA_NUM_THREADS="$threads" julia --project="$project" "$runner" \
                    --instances "$instances" --strategy "$row" --threads "$threads" \
                    --reps "$reps" --prime-ms "$prime_ms" --regime "$regime" \
                    --csv "$tmp" >&2
            fi
            if [ $first -eq 1 ]; then
                cat "$tmp" > "$csv"
                first=0
            else
                tail -n +2 "$tmp" >> "$csv"
            fi
            rm -f "$tmp"
            if [ -n "$diagnostics_csv" ]; then
                if [ "$row" = "$(echo "$rows" | cut -d, -f1)" ]; then
                    cat "$diag_tmp" > "$diagnostics_csv"
                else
                    tail -n +2 "$diag_tmp" >> "$diagnostics_csv"
                fi
                rm -f "$diag_tmp"
            fi
        done
        # A verify here establishes that the arm runs and writes its diagnostics; it does not compare
        # them with anything, because the reference lives in another arm. Saying "tolerance" would
        # claim a comparison this script never performed, so it says what it did.
        if [ "$command" = "verify" ]; then
            echo "verify: diagnostics written for $rows; the campaign compares them with the other arm"
        fi
        ;;
    *)
        echo "harness.sh: expected info, verify or run, got $command" >&2
        exit 2
        ;;
esac

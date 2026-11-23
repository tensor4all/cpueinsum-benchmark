#!/usr/bin/env python3
"""Turn the replay harness's own census into a frozen suite of the grouped-GEMM route campaign.

One suite is one (capture, dtype): every call record of that dtype in one capture file is a
family, and the suite's thread budgets are the widths the descriptor's `--width-capture`
assigns to that capture. The recorder passes a run's dtypes and budgets to every population
(`campaign_toolkit.record_run`, `runs[0]`), so a suite that mixed dtypes or captures would
declare cells the harness can only skip; split this way, a skipped cell is an exception that
names its reason (for example a `blas` call the vendor plan declined).

The census is the same untimed `verify` the recorder runs, with the descriptor's own
`measured.harness_args`, and the coverage check is the toolkit's `expected_cells`, shared with
`gen_suite_from_census.py`. Re-running against the same binary and corpus emits a byte-identical
file.

Usage:
    CAMPAIGN_DESCRIPTOR=benchmarks/grouped-m4max/campaign.yaml python3 scripts/gen_grouped_suite.py \\
        --binary target/cpueinsum-rev/0b5d091afe7f/bin/cpueinsum-replay \\
        --revision "$(git -C extern/cpueinsum-rs-grouped rev-parse HEAD)" \\
        --capture itebd-heff-b705d809-t4 --dtype float64 \\
        --out benchmarks/grouped-m4max/suites/grouped-m4max-t4-float64.yaml
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import pathlib
import shlex
import subprocess
import sys

import yaml
from campaign_toolkit import descriptor as toolkit_descriptor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_suite_from_census import Block, check_coverage, read_census  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGIME = "grouped"
ROWS = ["sequential", "outer", "auto", "inner", "blas"]
DTYPE_OF_RECORD = {"F64": "float64", "C64": "complex128"}
STALE_AFTER = 20

ENGINES_DOC = {
    "sequential": dict(
        provider="cpueinsum",
        summary="`cpueinsum::GroupedPlan` under `BatchStrategy::Sequential`: the jobs of the call "
                "one after another, each on the whole team.",
        identity="the measured cpueinsum-rs revision in this run's manifest (`library.commit`), "
                 "pinned by `pins/cpueinsum-rs-grouped.rev`",
        caveat="The reference of the checked twin: every other row is compared with it, bitwise, "
               "at the same width.",
    ),
    "outer": dict(
        provider="cpueinsum",
        summary="`GroupedPlan` under `BatchStrategy::Outer`: jobs split over lanes of the team, "
                "one thread per job.",
        identity="as `sequential`",
        caveat="A one-job call has one lane, so it runs serially; the observed route is in "
               "`route_observed`.",
    ),
    "auto": dict(
        provider="cpueinsum",
        summary="`GroupedPlan` under `BatchStrategy::Auto`: the route cpueinsum's current "
                "selector picks for the call and the width.",
        identity="as `sequential`",
        caveat="The selector is the subject of the fit this campaign feeds "
               "(tensor4all/cpueinsum-rs#80); its pick is recorded per cell in `route_observed`.",
    ),
    "inner": dict(
        provider="cpueinsum",
        summary="`GroupedPlan` under `BatchStrategy::Inner`: every job on all threads of the "
                "team, one after another.",
        identity="as `sequential`",
        caveat="The only native route that gives a one-job call more than one thread.",
    ),
}

# The `blas` row's provider is the descriptor's `engines.blas`; what the page says about it
# depends on which vendor that is.
VENDOR_DOC = {
    "accelerate": ("Accelerate on macOS", "Accelerate has no version or thread read-back"),
    "openblas": ("OpenBLAS on Linux",
                 "OpenBLAS reports its version and build (`openblas_get_config`), and its thread "
                 "count is set to the row's width and read back"),
}


def blas_doc(vendor):
    where, readback = VENDOR_DOC[vendor]
    return dict(
        provider=vendor,
        summary=f"`cpueinsum_blas::GroupedPlan` on the linked vendor ({where}), one "
                f"vendor GEMM per job inside the caller's team.",
        identity=f"the vendor the harness reports in `binary-info.txt` (`vendor.name`); "
                 f"{readback}",
        caveat="A call the vendor plan declines runs natively and is reported as a skipped "
               "cell, not timed as `blas`.",
    )


def placement(profile, widths):
    """The suite's `cpu_sets` for the profile and the blind spot that says how it is placed."""
    name = profile["name"]
    if profile.get("pinned") is False:
        # The recorder records every set of an unpinned profile as `unpinned` and never reads
        # this list (it is required by the schema and checked for size).
        return ({name: [f"0-{t - 1}" for t in widths]},
                f"The host is unpinned (`{name}`, `pinned: false`): the scheduler places "
                "threads, and width 16 includes the 4 efficiency cores. These cells are not "
                "comparable with a pinned profile's.")
    rows = {row["threads"]: row["measured"] for row in profile.get("thread_rows", [])}
    missing = [t for t in widths if t not in rows]
    if missing:
        sys.exit(f"ERROR: profile {name} has no thread row for widths {missing}")
    note = (f"The host is `{name}`, pinned by its thread rows. Its NUMA conditions (row "
            "placement, memory policy, automatic NUMA balancing) are the profile's `numa` "
            "block, and each run records the node layout and balancing it found in "
            "`host.numa`.")
    power = profile.get("power") or {}
    if power.get("cpufreq_boost") != "0" and power.get("intel_no_turbo") != "1":
        # The profile does not ask for boost off, so the host cannot switch it: the recorder
        # needs FBENCH_ALLOW_BOOST=1 and the manifest's host.power shows the state it ran in.
        note += (" Boost/turbo is not switched off on this host: runs are recorded under "
                 "`FBENCH_ALLOW_BOOST=1`, so cells compare within this host only and are not "
                 "a boost-off baseline.")
    return {name: [rows[t] for t in widths]}, note


def descriptor():
    path = pathlib.Path(os.environ.get("CAMPAIGN_DESCRIPTOR", ""))
    if not path.name:
        sys.exit("ERROR: set CAMPAIGN_DESCRIPTOR to the route campaign's descriptor")
    path = path if path.is_absolute() else ROOT / path
    return yaml.safe_load(path.read_text())


def option(args, flag):
    return args[args.index(flag) + 1]


def capture_families(corpus_dir, stem, dtype):
    """`<stem>:rNNN` for every call record of `dtype`, NNN counting call records from 0."""
    path = corpus_dir / f"{stem}.jsonl.gz"
    with gzip.open(path, "rt") as handle:
        provenance, *records = [json.loads(line) for line in handle]
    families = [f"{stem}:r{i:03d}" for i, r in enumerate(records)
                if DTYPE_OF_RECORD[r["dtype"]] == dtype]
    if not families:
        sys.exit(f"ERROR: {path} has no {dtype} call")
    return families, len(records), provenance["engine_threads"]


def run_census(binary, harness_args, thread, dtype, families, rows, out_path):
    cmd = [str(binary), "verify", *harness_args,
           "--threads", str(thread), "--n", "1", "--batch", "1", "--dtype", dtype,
           "--family", ",".join(families), "--rows", ",".join(rows),
           "--regime", REGIME, "--census-csv", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0 or "all comparisons within tolerance" not in proc.stdout:
        sys.exit(f"ERROR: census at {thread}T did not report a clean grid (exit "
                 f"{proc.returncode})\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return cmd


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--binary", required=True, type=pathlib.Path)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--capture", required=True, help="the capture stem this suite replays")
    ap.add_argument("--dtype", required=True, choices=sorted(DTYPE_OF_RECORD.values()))
    ap.add_argument("--profile", default="apple-m4max")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--rows", default=",".join(ROWS),
                    help="the engine rows this suite declares (default: all five); the "
                         "descriptor says why a suite leaves one out")
    args = ap.parse_args(argv)
    engine_rows = args.rows.split(",")
    if not engine_rows or any(r not in ROWS for r in engine_rows):
        sys.exit(f"ERROR: --rows must name rows of {ROWS}")

    d = descriptor()
    harness_args = list(d["measured"]["harness_args"])
    corpus_dir = ROOT / option(harness_args, "--corpus-dir")
    widths = sorted(int(w) for w, stem in
                    (entry.split("=") for entry in option(harness_args, "--width-capture").split(","))
                    if stem == args.capture)
    if not widths:
        sys.exit(f"ERROR: the descriptor's --width-capture assigns no width to {args.capture}")
    families, records, engine = capture_families(corpus_dir, args.capture, args.dtype)
    profiles = {p["name"]: p for p in toolkit_descriptor.load_descriptor(ROOT).profiles()}
    if args.profile not in profiles:
        sys.exit(f"ERROR: {args.profile} is not a profile of {d['profiles_file']}")
    cpu_sets, placement_note = placement(profiles[args.profile], widths)

    workdir = ROOT / "target/census" / REGIME
    workdir.mkdir(parents=True, exist_ok=True)
    commands, rows = [], []
    for t in widths:
        path = workdir / f"{args.out.stem}-{t}t.census.csv"
        commands.append(run_census(args.binary, harness_args, t, args.dtype, families,
                                   engine_rows, path))
        rows.extend(read_census(path))
    skipped = [r for r in rows if r["status"] == "skipped"]

    suite = {
        "schema_version": 1,
        "id": args.out.stem,
        "description": Block(
            f"The grouped GEMM calls symtn issued in an iTEBD + H_eff run, replayed call by call "
            f"by `cpueinsum-replay` out of the pinned `cpueinsum-rs` checkout. Capture "
            f"`{args.capture}` (symtn engine width {engine}), {args.dtype} calls only: one family per call "
            f"record, one engine row per `GroupedPlan` route. The rows are routes of one "
            f"library plus the vendor GEMM loop of `cpueinsum-blas`, so a table here is a route "
            f"comparison inside cpueinsum, not a comparison of implementations. The declared "
            f"identity shape is the sentinel `n = 1`: each call fixes its own job list, which "
            f"travels in the harness's `case_m` (jobs), `case_n` (total m*n*k), `case_k` "
            f"(output elements) and `job_m/n/k` (largest job) columns."),
        "invalidated_by": list(d["default_invalidated_by"]),
        "stale_after": STALE_AFTER,
        "required_profiles": [],
        "optional_profiles": [args.profile],
        "family_groups": {REGIME: families},
        "workloads": {
            "name": Block(f"symtn grouped-GEMM corpus, {args.capture}, {args.dtype}"),
            "description": Block(
                "Spin-1/2 Heisenberg chain with U(1) and SU(2) symmetry: iTEBD with SVD "
                "truncation at chi = 64, 256 and 1024 states, then the two-site H_eff matvec on "
                "the converged bond. Every grouped GEMM call the default dense executor "
                "received, identical calls merged with a multiplicity. The job list of a call "
                "(offsets, m, n, k, leading dimensions) is the capture's; the operand values are "
                "the harness's small-integer fill."),
            "source": Block(
                f"`gemm-trace-corpus/{args.capture}.jsonl.gz` of Ryo-wtnb11/symtn-rs at "
                f"`pins/symtn-gemm-trace.rev`, materialised by `scripts/setup_extern_deps.sh`, "
                f"which refuses a file whose SHA-256 is not the one the corpus README lists. "
                f"{len(families)} of the capture's {records} call records have this dtype."),
            "known_blind_spots": [
                "A sample is warm-cache back-to-back replay of one call; the cache state "
                "between the calls of the real run is not reproduced.",
                placement_note,
                "Per-call grouping depends on symtn's engine width at capture: widths 1, 4 and "
                "8 replay the 4-thread capture, full width replays the full-width capture.",
                "Every call has ops N,N and alpha = 1, and no call is non-compact: lazy "
                "adjoints, scaled updates and leading dimensions are not exercised.",
                "No DMRG sweep: H_eff on the iTEBD-converged bond stands in for the Lanczos "
                "matvec.",
                "First touch of every buffer is on the main thread.",
            ],
        },
        "runs": [{
            "threads": widths,
            "cpu_sets": cpu_sets,
            "dtypes": [args.dtype],
            "engines": engine_rows,
            "populations": [{"regime": REGIME, "groups": [REGIME], "n": ["1"], "batch": [1]}],
        }],
        "engines_doc": {row: doc for row, doc in
                        {**ENGINES_DOC, "blas": blas_doc(d["engines"]["blas"])}.items()
                        if row in engine_rows},
    }
    expected = check_coverage(suite, rows)
    header = [
        "# GENERATED by scripts/gen_grouped_suite.py -- do not edit by hand.",
        f"# Harness: {args.binary} (cpueinsum-replay)   Source revision: {args.revision}",
        "# Census (untimed `verify`, at every declared width):",
        *[f"#   {shlex.join(c[:c.index('--family') + 1] + ['<families>'] + c[c.index('--family') + 2:])}"
          for c in commands],
        f"# Families: {len(families)} {args.dtype} call records of {args.capture} "
        f"({records} records); widths: {', '.join(map(str, widths))}; "
        f"census: {len(rows)} cells, {len(skipped)} skipped.",
        *[f"# Skipped in the census: {r['row']} {r['family']} {r['threads']}T -- {r['note']}"
          for r in skipped],
        "",
    ]
    text = "\n".join(header) + yaml.safe_dump(suite, sort_keys=False, default_flow_style=False,
                                              allow_unicode=True, width=100)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(f"wrote {args.out}: {len(families)} families, widths {widths}, "
          f"{len(expected)} declared cells, {len(skipped)} skipped in the census")
    return 0


if __name__ == "__main__":
    sys.exit(main())

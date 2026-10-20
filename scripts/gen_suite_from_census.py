#!/usr/bin/env python3
"""Turn the pinned harness's own census into a frozen timing-v2 suite declaration.

The census is the harness's declaration of the cell grid it covers: `verify` writes
one row per `(regime, family, dtype, order, m, n, k, batch, row, threads)` with a
`status` and a `note`, untimed and at the smallest declared setting. This script runs
that census against the campaign's harness entry point, folds it into a toolkit suite
(one family per corpus instance, the harness's regime as the single family group), and
refuses to emit anything whose census does not cover exactly the product the
declaration would require a run to measure.

The generated file is committed and then frozen; nothing rebuilds it. Re-running the
script against the same binary and corpus emits a byte-identical file, so a diff is a
real change in the corpus or in the harness's census.

Usage:
    python3 scripts/gen_suite_from_census.py \
        --binary target/cpueinsum-rev/1030db32c860/bin/cpueinsum-bench \
        --instances extern/tenferro-einsum-benchmark/data/instances \
        --revision 1030db32c860db4f8d2d76f29d97ff91378dc0e8 \
        --out benchmarks/suites/cpueinsum.yaml

`--binary` is the built harness artifact (`BIN_DIR/cpueinsum-bench` in the descriptor).
The generator runs the same census the recorder will, and passes `--instances` itself;
at record time the descriptor's `measured.harness_args` supplies it instead.

The toolkit must be importable (it is pinned in `requirements.txt`); the declaration
check is the same `campaign_toolkit.timing_evidence.expected_cells` the recorder and
the validator use, not a re-implementation.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import shlex
import subprocess
import sys

import yaml

CENSUS_HEADER = ["regime", "family", "dtype", "order", "m", "n", "k",
                 "batch", "row", "threads", "status", "note"]

# Corpus instances this campaign does not declare, with the reason recorded in the
# generated file. An entry here is a *declaration* decision, not a silence: the census is
# taken over the remaining instances, and the reason is printed in the suite's prose and
# therefore on every page. CI checks the declared families against the pinned corpus
# minus exactly these names.
#
# `str_mps_varying_inner_product_200` (200 operands, 199 steps, a rank-0 output) is
# refused by the harness's own cross-row verification at every declared thread budget:
#
#   verify: 28 declared cell(s), 27 ok, 0 skipped, 1 failed
#   MISMATCH opt_flops str_mps_varying_inner_product_200 float64 1 MISMATCH(opt_flops) rel_err=NaN
#   exit 1
#
# The refusal is deterministic (1T and 4T, both row orders: whichever row is compared
# second is the one reported) and it is a property of the instance at its own extents
# rather than of the contraction structure: with every extent set equal to 2 or 8 the two
# declared orders agree on the same instance, 9, 10, 13 and 15 agree, and 11, 12, 14 and
# 16-19 do not. The harness's comparison needs both rows' outputs to be finite - it
# squares them, so a NaN there means one of the two orders returned `inf`/NaN at those
# extents. The corpus's own runner generates zero-filled tensors and never compared
# values, so the corpus's pipeline would not have caught it. A cell that *fails* is not a
# declared skip in the toolkit's evidence contract (`timing_evidence.validate` accepts
# only `ok` and `skipped`), so the only coherent declaration is one that omits the
# instance; a page that claimed it would be claiming a measurement the harness refused.
# See `docs/verify-refusal-str_mps-varying-inner-product-200.md`.
EXCLUDED = {
    "str_mps_varying_inner_product_200": (
        "the harness's own cross-row verification refuses it (`MISMATCH(opt_flops) "
        "rel_err=NaN`, exit 1) at every declared thread budget"
    ),
}

REGIME = "cpueinsum"
ROWS = ["opt_size", "opt_flops"]
DTYPES = ["float64"]
N = "1"
BATCH = "1"
THREADS = [1, 4]
CPU_SETS = ["4", "4-7"]
STALE_AFTER = 20
OPTIONAL_PROFILES = ["zen5-cpu"]

DESCRIPTION = (
    "The `tenferro-einsum-benchmark` instance corpus, measured by `cpueinsum-bench` out of "
    "the pinned `cpueinsum-rs` checkout. One family per instance and one engine row per "
    "contraction order the corpus declares for it (`opt_size`, `opt_flops`), so the only "
    "thing that varies across a row is the order cpueinsum executes. The declared identity "
    "shape is the numeric sentinel `n = 1`: each instance fixes its own extents, so there is "
    "no shape knob to sweep and the real operand geometry travels beside the sentinel in the "
    "harness's own `case_m`/`case_n`/`case_k` columns. One corpus instance is deliberately "
    "absent; the blind spots below name it and say why."
)

INVALIDATED_BY = [
    "crates/cpueinsum-bench/**",
    "crates/cpueinsum/**",
    "Cargo.toml",
    "Cargo.lock",
]

WORKLOADS = dict(
    name="Einsum instance corpus",
    description=(
        "One whole einsum per instance, from the `tenferro-einsum-benchmark` problem set: "
        "pairwise matrix products, batched and elementwise products, outer products, a "
        "matrix-chain problem, MPS inner products, two MERA networks, two tensor-network "
        "permutation problems, and two likelihood contractions of 38 and 84 operands. The "
        "operands are generated by the harness (deterministic, dtype-templated) and the "
        "contraction order is taken from the corpus's own `paths` entry, so the rows measure "
        "one library against two declared schedules, not two libraries."
    ),
    source=(
        "The corpus is `tenferro-einsum-benchmark` `data/instances/*.json` at the revision in "
        "`pins/tenferro-einsum-benchmark.rev`, materialised by `scripts/setup_extern_deps.sh`. "
        "Each instance declares `name`, `format_string`, `shapes`, `dtype` and two "
        "opt_einsum-style positional paths; `crates/cpueinsum-bench/src/corpus.rs` in the "
        "measured revision translates them into cpueinsum's integer-label, SSA-order API."
    ),
    known_blind_spots=[
        *[f"The corpus instance `{name}` is **not declared**: {reason}. It is therefore not "
          f"measured, not skipped, and not part of this suite's coverage; the evidence is in "
          f"`docs/verify-refusal-str_mps-varying-inner-product-200.md`."
          for name, reason in sorted(EXCLUDED.items())],
        "The declared identity is the numeric sentinel `n = 1`: every instance has fixed "
        "extents, so the declaration grid has one shape and the real operand shapes are the "
        "harness's `case_m` (operand count), `case_n` (total input elements) and `case_k` "
        "(output elements) columns, not geometry the toolkit compares.",
        "The engine rows are two contraction orders of the same library, so a row here is a "
        "schedule comparison inside cpueinsum, not a comparison against an independent "
        "implementation; there is no reference engine and no vendor arm in the first record.",
        "Every instance has unit batch, so a cost proportional to batch elements is invisible.",
        "One size per instance: a ratio here says nothing about a neighbouring instance, and "
        "the set is not a sweep.",
        "A corpus revision is not one of the measured repository's `invalidated_by` paths: the "
        "declaration records the corpus pin it was generated from, and a corpus bump has to be "
        "a deliberate regeneration of this suite.",
    ],
)

ENGINES_DOC = {
    "opt_size": dict(
        provider="cpueinsum",
        summary="cpueinsum executing the corpus's `paths.opt_size` order: the order the "
                "corpus declares as minimizing the largest intermediate (memory).",
        identity="the measured cpueinsum-rs revision in this run's manifest "
                 "(`library.commit`), pinned by `pins/cpueinsum-rs.rev`",
        caveat="The order is the caller's, taken verbatim from the corpus; no order is "
               "searched or corrected here.",
    ),
    "opt_flops": dict(
        provider="cpueinsum",
        summary="cpueinsum executing the corpus's `paths.opt_flops` order: the order the "
                "corpus declares as minimizing the operation count.",
        identity="the measured cpueinsum-rs revision in this run's manifest "
                 "(`library.commit`), pinned by `pins/cpueinsum-rs.rev`",
        caveat="The two orders coincide for most instances in this corpus; where they do, a "
               "small difference between the rows is measurement noise, not a scheduling "
               "effect.",
    ),
}


class Block(str):
    """A string emitted as a YAML block scalar, so generated prose stays readable."""


def block_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.add_representer(Block, block_representer, Dumper=yaml.SafeDumper)


def corpus_families(instances_dir):
    """The instance names the pinned corpus carries: the `name` field of every `*.json`."""
    import json
    names = [json.loads(p.read_text())["name"] for p in sorted(pathlib.Path(instances_dir).glob("*.json"))]
    if not names:
        sys.exit(f"ERROR: no *.json instance files in {instances_dir}")
    return sorted(names)


def declared_families(instances_dir):
    """The corpus's instances minus the documented exclusions; the two must agree.

    A corpus bump that renamed or dropped an excluded instance must fail here rather than
    silently let it back into the declaration.
    """
    names = corpus_families(instances_dir)
    unknown = sorted(set(EXCLUDED) - set(names))
    if unknown:
        sys.exit(f"ERROR: {instances_dir} has no instance named {unknown}; the documented "
                 f"exclusion in this script refers to a corpus that has moved")
    return [n for n in names if n not in EXCLUDED]


def run_census(binary, thread, args, out_path):
    """Run one untimed `verify` census pass and return the argv used.

    `--family` is the declaration's own instance list: the harness would otherwise verify
    every instance the corpus holds, including the ones this campaign documents as excluded.
    """
    cmd = [str(binary), "verify",
           "--threads", str(thread),
           "--n", args.n,
           "--batch", args.batch,
           "--dtype", ",".join(args.dtypes),
           "--family", ",".join(args.families),
           "--rows", ",".join(args.rows),
           "--regime", REGIME,
           "--instances", str(args.instances),
           "--census-csv", str(out_path),
           # A declaration with one engine row has no sibling to compare against, so its census
           # needs the other arm's diagnostics. Arguments here reach `verify` only: a suite
           # generated from a census is still measured without them.
           *[tok for chunk in (args.verify_args or []) for tok in chunk.split()]]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ERROR: census failed at {thread}T (exit {proc.returncode})\n"
                 f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    if "all comparisons within tolerance" not in proc.stdout:
        sys.exit(f"ERROR: census at {thread}T did not report a clean grid; refusing to emit a "
                 f"suite from an unverified census")
    return cmd


def read_census(path):
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in CENSUS_HEADER if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"ERROR: {path}: census is missing the column(s) {missing}; expected at "
                     f"least {CENSUS_HEADER}. The harness's census contract changed.")
        rows = list(reader)
    for row in rows:
        if row["status"] not in ("ok", "skipped"):
            sys.exit(f"ERROR: {path}: census cell {row} has status {row['status']!r}; a suite is "
                     f"generated only from a census whose cells are all ok or skipped")
    return rows


def build_suite(args, rows):
    families = sorted({row["family"] for row in rows})
    if not families:
        sys.exit("ERROR: the census is empty; nothing to declare")
    seen_dtypes = {row["dtype"] for row in rows}
    dtypes = list(dict.fromkeys(args.dtypes))
    if set(dtypes) != seen_dtypes:
        sys.exit(f"ERROR: the census covers dtypes {sorted(seen_dtypes)}, not the declared "
                 f"{dtypes}; refusing to emit a suite with a dtype the census does not cover")
    threads = sorted({int(row["threads"]) for row in rows})
    suite = {
        "schema_version": 1,
        "id": REGIME,
        "description": Block(DESCRIPTION),
        "invalidated_by": list(INVALIDATED_BY),
        "stale_after": STALE_AFTER,
        # No run exists yet, so the cell is optional; the first recorded cell can move it to
        # required (see `docs/results.md`).
        "required_profiles": [],
        "optional_profiles": list(OPTIONAL_PROFILES),
        "family_groups": {REGIME: families},
        "workloads": {k: Block(v) if isinstance(v, str) else v for k, v in WORKLOADS.items()},
        "runs": [
            {
                "threads": threads,
                "cpu_sets": [CPU_SETS[THREADS.index(t)] for t in threads],
                "dtypes": dtypes,
                "engines": list(args.rows),
                "populations": [
                    {
                        "regime": REGIME,
                        "groups": [REGIME],
                        "n": [args.n],
                        "batch": [int(args.batch)],
                    }
                ],
            }
        ],
        "engines_doc": ENGINES_DOC,
    }
    return suite, families, dtypes, threads


def check_coverage(suite, rows):
    """The census cell set must equal the product the declaration requires.

    The product is the toolkit's own `expected_cells`, computed over the suite being
    emitted, so the generator, the recorder and the validator cannot disagree about what
    the declaration covers.
    """
    from campaign_toolkit import timing_evidence

    spec = suite["runs"][0]
    manifest = {
        "run_spec": {
            "populations": [
                {"regime": p["regime"],
                 "families": sorted(f for g in p["groups"] for f in suite["family_groups"][g]),
                 "n": p["n"], "batch": p["batch"]}
                for p in spec["populations"]
            ],
            "dtypes": spec["dtypes"],
            "engines": spec["engines"],
        },
        "threads": {"counts": spec["threads"]},
    }
    expected = timing_evidence.expected_cells(manifest)
    observed = {timing_evidence.cell(row)[:-1] for row in rows}
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        sys.exit("ERROR: the census does not cover the declared product; refusing to emit a suite\n"
                 f"  {len(missing)} declared cell(s) absent from the census, up to 5: {missing[:5]}\n"
                 f"  {len(extra)} census cell(s) not declared, up to 5: {extra[:5]}")
    return expected


def header_comment(args, commands, families, dtypes, threads):
    lines = [
        "# GENERATED by scripts/gen_suite_from_census.py -- do not edit by hand.",
        f"# Harness: {args.binary} (cpueinsum entry point)   "
        f"Source revision: {args.revision}",
        "# Census (untimed `verify`, at every declared thread budget):",
    ]
    for cmd in commands:
        lines.append(f"#   {shlex.join(cmd)}")
    lines += [
        f"# Families: {len(families)} of the {len(families) + len(EXCLUDED)} instances of the "
        f"pinned corpus; groups: 1 ({REGIME}); dtypes: {', '.join(dtypes)}; threads: "
        f"{', '.join(str(t) for t in threads)}.",
        *[f"# Not declared: {name} -- {reason}." for name, reason in sorted(EXCLUDED.items())],
        f"# The declared identity shape is the numeric sentinel `n = {args.n}`: see the suite's "
        f"description and blind spots.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--binary", required=True, type=pathlib.Path,
                    help="the campaign's harness entry point (BIN_DIR/cpueinsum-bench)")
    ap.add_argument("--revision", required=True,
                    help="the measured revision the harness was built from (for the header)")
    ap.add_argument("--instances", required=True, type=pathlib.Path,
                    help="the pinned corpus's data/instances directory")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="the suite YAML to write")
    ap.add_argument("--rows", default=None, help="engine rows, comma separated")
    ap.add_argument("--dtype", dest="dtypes", default=None, help="dtypes, comma separated")
    ap.add_argument("--n", default=N, help="the declared size spec")
    ap.add_argument("--batch", default=BATCH, help="the declared batch")
    ap.add_argument("--threads", default=None, help="thread budgets, comma separated")
    ap.add_argument("--verify-args", action="append", default=[],
                    help="extra arguments for the census `verify` (for example "
                         "--reference-csv PATH when the declaration carries a single row)")
    ap.add_argument("--workdir", default=None, type=pathlib.Path,
                    help="where the temporary census files go (default: target/census/cpueinsum)")
    args = ap.parse_args(argv)

    if not args.binary.exists():
        sys.exit(f"ERROR: {args.binary} does not exist; build the harness first "
                 f"(scripts/build_for_cpueinsum_rev.sh)")
    args.families = declared_families(args.instances)
    args.rows = [r for r in (args.rows.split(",") if args.rows else ROWS) if r]
    args.dtypes = list(dict.fromkeys(
        d for d in (args.dtypes.split(",") if args.dtypes else DTYPES) if d))
    args.threads = [int(t) for t in (args.threads.split(",") if args.threads else THREADS)]
    unknown = [r for r in args.rows if r not in ROWS]
    if unknown:
        sys.exit(f"ERROR: {unknown} is not one of this harness's measurable engine rows {ROWS}")
    unknown = [t for t in args.threads if t not in THREADS]
    if unknown:
        sys.exit(f"ERROR: no declared CPU set for the thread budget(s) {unknown}; add it here "
                 f"and to the suite declaration")

    workdir = args.workdir or pathlib.Path("target/census") / REGIME
    workdir.mkdir(parents=True, exist_ok=True)
    commands, rows = [], []
    for thread in args.threads:
        census_path = workdir / f"{REGIME}-{thread}t.census.csv"
        commands.append(run_census(args.binary, thread, args, census_path))
        rows.extend(read_census(census_path))

    suite, families, dtypes, threads = build_suite(args, rows)
    expected = check_coverage(suite, rows)
    text = header_comment(args, commands, families, dtypes, threads)
    # The reference the census was checked against is part of the declaration: a run of this suite
    # verifies against the same file, and a suite whose verify_args were dropped would refuse to
    # record at all (its single row has no sibling) or, worse, be recorded unverified.
    # One campaign, several suites: a declaration is named after the file it lives in, and the
    # validator finds a run's declaration by that id. A suite called `einsum-opt_size` that still
    # carried the campaign's id would make every run of it unresolvable.
    suite["id"] = pathlib.Path(args.out).stem
    if args.verify_args:
        suite["verify_args"] = [tok for chunk in args.verify_args for tok in chunk.split()]
    text += yaml.safe_dump(suite, sort_keys=False, default_flow_style=False,
                           allow_unicode=True, width=100)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(f"wrote {args.out}: {len(families)} families, {len(dtypes)} dtypes, "
          f"{len(args.rows)} engines, {len(expected)} declared cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())

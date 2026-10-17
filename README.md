# cpueinsum-benchmark

The benchmark campaign for [cpueinsum-rs](https://github.com/tensor4all/cpueinsum-rs):
results keyed by **library commit × hardware profile**, with the staleness of every cell
visible rather than implied.

| | |
|---|---|
| Latest results | [`result-v2/cpueinsum/INDEX.md`](result-v2/cpueinsum/INDEX.md) — generated table of contents over the per-revision pages |
| Declaration | [`benchmarks/suites/cpueinsum.yaml`](benchmarks/suites/cpueinsum.yaml) — the frozen suite, generated from the pinned harness's own census |
| Reference revision | [`pins/cpueinsum-rs.rev`](pins/cpueinsum-rs.rev) — what `status` is measured against |
| Agent workflow | [`AGENTS.md`](AGENTS.md) — how a run is taken, and what must not be worked around |

## What is measured

`cpueinsum-bench` runs each problem of the [einsum instance
corpus](https://github.com/tensor4all/tenferro-einsum-benchmark) twice, once per contraction
order the corpus declares for it:

| engine row | what it is |
|---|---|
| `opt_size` | the corpus's `paths.opt_size` order — the one that minimizes the largest intermediate |
| `opt_flops` | the corpus's `paths.opt_flops` order — the one that minimizes the operation count |

Both rows are the same library, so a table is a comparison of two schedules inside
cpueinsum, not of two implementations. There is no vendor arm and no external reference in
this first record; the corpus's two declared orders are the campaign's only engine rows.
Every instance fixes its own extents, so the declared identity shape is the numeric sentinel
`n = 1` and the real operand geometry travels in the harness's own `case_m`/`case_n`/`case_k`
columns.

Thirteen of the corpus's fourteen instances are declared.
`str_mps_varying_inner_product_200` is refused by the harness's own cross-row verification at
every thread budget (`MISMATCH(opt_flops) rel_err=NaN`, exit 1), so a declaration containing
it cannot be recorded; the evidence and the decision are in
[`docs/verify-refusal-str_mps-varying-inner-product-200.md`](docs/verify-refusal-str_mps-varying-inner-product-200.md),
and the omission is printed in the suite and on every page that quotes it.

The harness lives in the measured repository (`crates/cpueinsum-bench`) and is built out of
the same checkout as the library it measures, so the recorded commit describes both.

## How it works

The campaign owns its declarations, its pins and its launcher; the machinery is the shared
[`campaign-toolkit`](https://github.com/tensor4all/campaign-toolkit), pinned in
`requirements.txt` and in `pins/campaign-toolkit.rev`.

```bash
./scripts/setup_extern_deps.sh      # clone cpueinsum-rs and the instance corpus, at their pins
./scripts/setup_extern_deps.sh --measured ../cpueinsum-rs --corpus ../tenferro-einsum-benchmark

# regenerate the frozen suite from the pinned harness's own census (only when the
# harness or the corpus moves; the committed file is what CI checks)
python3 scripts/gen_suite_from_census.py \
    --binary target/cpueinsum-rev/1030db32c860/bin/cpueinsum-bench \
    --instances extern/tenferro-einsum-benchmark/data/instances \
    --revision "$(git -C extern/cpueinsum-rs rev-parse HEAD)" \
    --out benchmarks/suites/cpueinsum.yaml

# record one cell: build, verify, measure, validate, report, publish, reindex
python3 scripts/v2/record_run.py zen5-cpu cpueinsum

# check that the committed index is what the generator produces
python3 scripts/v2/gen_index.py --check
```

The timing contract is frozen in the descriptor (`benchmarks/campaign.yaml`): median of 5
chronological calls per cell, 2 complete process sets — one whole rotation cycle over the
two declared engine rows — and at least 250 ms of untimed priming per cell, at 1 thread on
CPU 4 and 4 threads on CPUs 4-7 of the `zen5-cpu` profile. Cells are recorded under a
rotating engine order and the raw per-call samples are kept in the run directory.

`BIN_DIR/cpueinsum-bench` is this repository's entry point
([`scripts/harness_launcher.sh`](scripts/harness_launcher.sh)), not the cargo artifact: the
harness requires the instance corpus on its command line and the shared recorder has no
field for a harness input path, so the campaign binds the pinned harness to the pinned
corpus. The manifest's `binary.sha256` is therefore the launcher's hash, and the launcher
prints the artifact it dispatches to on `info` (kept in the run's `binary-info.txt`).

## What this repository is not

It is not the library's per-PR suite. cpueinsum-rs keeps its own tests and gates; this
repository owns the campaign: the declarations, the pins, the run manifests, the index and
the published pages. It does not vendor the corpus, and it does not own the harness.

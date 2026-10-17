# Why `str_mps_varying_inner_product_200` is not declared

Status: **a declaration decision with its evidence recorded here.** Nothing in the toolkit,
the measured repository or the corpus was changed for it.

## What happens

The pinned harness refuses to verify one of the fourteen instances of the pinned corpus, at
every declared thread budget, on every run, in both row orders:

```console
$ cpueinsum-bench verify --threads 4 --n 1 --batch 1 --dtype float64 \
      --family bin_batched_matmul_b32_m64_n64_k64,...,str_mps_varying_inner_product_200,... \
      --rows opt_size,opt_flops --regime cpueinsum --census-csv target/census/cpueinsum/cpueinsum-4t.census.csv
verify: 28 declared cell(s), 27 ok, 0 skipped, 1 failed
MISMATCH opt_flops str_mps_varying_inner_product_200 float64 1 MISMATCH(opt_flops) rel_err=NaN
wrote target/census/cpueinsum/cpueinsum-4t.census.csv
exit 1
```

The failing cell in that census CSV is

```
cpueinsum,str_mps_varying_inner_product_200,float64,,1,1,,1,opt_flops,4,failed,MISMATCH(opt_flops) rel_err=NaN
```

`verify` exits non-zero, so `campaign_toolkit.record_run` aborts at its verification pass and
publishes nothing. Exactly one cell fails; the other 27 are `ok` and none is `skipped`.

## Where the refusal comes from

* `crates/cpueinsum-bench/src/harness.rs` — `grid` marks the second and later rows of a case
  `Failed` when `rel_error` exceeds `T::TOLERANCE`, with the note
  `MISMATCH({row}) rel_err={error:.2e}`; `run_grid` returns `all_ok = false`, and
  `crates/cpueinsum-bench/src/main.rs` (the `Mode::Verify` arm of `measure`) turns that into
  `ExitCode::FAILURE`.
* `campaign_toolkit/record_run.py:691-701` — the recorder's verify pass exits with
  `ERROR: verify failed for cpueinsum 4T ...; nothing published`.
* `campaign_toolkit/timing_evidence.py:validate` accepts only `ok` and `skipped` census
  cells, so a `failed` cell is not a declared skip that a page could carry.

## Evidence that it is the instance and not the campaign

Repeating the run is deterministic: `rel_err=NaN` at 1T and at 4T, and with the rows given as
`opt_flops,opt_size` the *compared* row is reported instead — whichever row is verified second
is the failing one.

`rel_error` is `||got - want|| / ||want||` with `want` the first-executed row's output. A NaN
there needs an `inf` or a NaN in one of the two outputs, because both the numerator and the
denominator square their terms; so the two declared orders do not return the same finite value
for this instance.

Two probes point at the instance's own extents rather than at the contraction structure. Both
were run against a copy of the instance whose `shapes` were rewritten so that every extent
equals the same value `d` (the format string and both positional paths unchanged), so the
declared contraction is the same problem at smaller extents:

| every extent `d` | f64 result | f32 result |
|---|---|---|
| 2, 8, 9, 10, 13, 15 | both rows agree | both rows `rel_err=NaN` |
| 11, 12, 14, 16, 17, 18, 19 | `rel_err=NaN` | not run |

At `d = 2` the values are far from the f64 range in either direction and the two orders agree,
so the translation of both paths into cpueinsum's SSA form is agreed on the same contraction.
The failure appears only once the operands are large enough for the magnitudes to matter, and
its pattern is not monotone in `d` — which is why this is recorded as "at these extents the two
schedules do not return the same finite value", not as "the harness is wrong".

The corpus's own runner generates **zero-filled** tensors (`tenferro-einsum-benchmark` README:
"tensors are generated at benchmark time (zero-filled)") and never compared values, so the
corpus's pipeline could not have seen this; and the harness's data are unit-magnitude, which is
what makes an *unnormalized* 200-operand inner product ill-conditioned in the first place.

## What was decided

The campaign declares the thirteen instances the harness certifies. The omission is stated in
the generated suite (its description and its blind spots), in
`scripts/gen_suite_from_census.py` next to the exclusion list, and on every page that quotes
it; `.github/workflows/ci.yml` checks the declared families against the pinned corpus *minus*
that list, so a corpus bump cannot quietly change what is excluded.

Two alternatives were rejected:

* editing the harness or the corpus to make this instance verifiable — the task this campaign
  was built under forbids touching either, and a campaign that edits the thing it measures is
  not a measurement;
* declaring the instance and recording a partial run over the other thirteen — the toolkit
  derives `expected_cells` from the declaration, so a run that skips a declared cell is
  `failed` evidence, not `partial` coverage, and the declaration would then be claiming a cell
  the harness refused.

If the harness is fixed (or the instance is normalised), delete the entry from `EXCLUDED` and
regenerate the suite: the census will then cover fourteen families and the page will too.

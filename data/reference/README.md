# Cross-arm reference diagnostics

`omeinsum-<strategy>.csv` is what the OMEinsum.jl arm (`scripts/julia/einsum_runner.jl`) computes for
every corpus instance, in the format `cpueinsum-bench verify --diagnostics-csv` writes and
`verify --reference-csv` reads. A strategy suite with one measured row has no sibling to compare
against, so its verify is checked against this file instead.

* the arm: OMEinsum 0.9.4, package set pinned in `scripts/julia/Manifest.toml`;
* the run: `julia --project=scripts/julia scripts/julia/einsum_runner.jl --instances
  extern/tenferro-einsum-benchmark/data/instances --strategy <strategy> --threads 1 --reps 1
  --prime-ms 0 --csv <tmp> --diagnostics-csv data/reference/omeinsum-<strategy>.csv`;
* the values: `sum`, `sum_sq`, `max_abs`, and a weighted sum whose weights are SplitMix64 of the
  element's row-major linear index (campaign-toolkit `docs/cross-implementation-verification.md`);
* the key: `regime|family|dtype|m|n|k|batch`, without the row name, because two arms name the same
  work differently.

**Regenerate this whenever the corpus pin moves.** The file is evidence about a corpus revision, and
the instance set is the corpus's, not this campaign's. Against the Rust harness the two arms agree to
7.3e-14 relative, three orders of magnitude inside the 1e-9 the check allows.

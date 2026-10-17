# extern/

Checkouts this repository builds and measures against, produced by
`scripts/setup_extern_deps.sh`. Nothing here is committed: each is a clone (or a
symlink to a local checkout) whose revision is recorded per run in `run.yaml`, and the
*reference* revision that `result-v2/INDEX.md` measures staleness against is
`pins/cpueinsum-rs.rev`.

| path | what | pin |
|---|---|---|
| `cpueinsum-rs` | the measured library and the harness it carries (`crates/cpueinsum-bench`) | `pins/cpueinsum-rs.rev` |
| `tenferro-einsum-benchmark` | the einsum instance corpus (`data/instances/*.json`) the harness reads | `pins/tenferro-einsum-benchmark.rev` |

The corpus is an input to the harness, not a dependency of the measured library: it is
materialised here so that the harness is pointed at a checkout whose revision can be
stated, instead of at whatever instance directory a machine happened to have.

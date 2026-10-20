#!/usr/bin/env julia
# OMEinsum.jl arm for the cpueinsum corpus, measured the way the Rust harness measures it.
#
# The point of this runner is that the two arms compute **the same thing from the same
# operands**, so a difference between them is a performance difference and not a
# different question. Three things therefore have to match the harness exactly, and each
# is spelled out where it happens below:
#
#   * the operands: `unit(i)` for the linear index `i`, in row-major order, which is what
#     `Elem::sample` fills the Rust side's buffers with;
#   * the contraction order: the corpus's own `paths.<strategy>.path`, executed pairwise,
#     never OMEinsum's optimizer - this arm measures the execution of a declared schedule,
#     not the search for one;
#   * the diagnostics: `sum`, `sum_sq`, `max_abs` and a weighted sum whose weights are
#     SplitMix64 of the element's row-major linear index, so a permutation cannot pass by
#     accident (see campaign-toolkit `docs/cross-implementation-verification.md`).
#
# Usage:
#   julia --project=scripts/julia scripts/julia/einsum_runner.jl \
#       --instances <corpus dir> --strategy opt_size --threads 1 \
#       --reps 5 --prime-ms 250 --csv <timing.csv> --diagnostics-csv <diagnostics.csv>

using JSON
using OMEinsum
using Printf

const UNIT_GOLDEN = 0.6180339887498949

"""The deterministic datum the Rust harness fills its operands with (`elem.rs::unit`)."""
unit(i::Int) = begin
    x = (i + 0.5) * UNIT_GOLDEN
    (x - floor(x)) * 2.0 - 1.0
end

"""The weight of linear index `i`, identical to `diagnostics.rs::weight`."""
function weight(i::Int)
    z = UInt64(i) * 0x9E3779B97F4A7C15
    z = (z ⊻ (z >> 30)) * 0xBF58476D1CE4E5B9
    z = (z ⊻ (z >> 27)) * 0x94D049BB133111EB
    z = z ⊻ (z >> 31)
    Float64(z >> 11) / 9007199254740992.0
end

"""Row-major strides of `dims` (the harness's `row_major`)."""
function row_major_strides(dims::Vector{Int})
    n = length(dims)
    strides = ones(Int, n)
    for k in (n - 1):-1:1
        strides[k] = strides[k + 1] * dims[k + 1]
    end
    strides
end

"""An array whose element at row-major index `i` is `unit(i)`, axes in declaration order."""
function operand(dims::Vector{Int})
    isempty(dims) && return fill(unit(0))
    A = Array{Float64}(undef, dims...)
    strides = row_major_strides(dims)
    for I in CartesianIndices(A)
        lin = 0
        @inbounds for k in eachindex(dims)
            lin += (I[k] - 1) * strides[k]
        end
        A[I] = unit(lin)
    end
    A
end

parse_format(fmt::AbstractString) = begin
    parts = split(fmt, "->"; limit = 2)
    lhs = parts[1]
    rhs = length(parts) > 1 ? parts[2] : ""
    ([collect(Char, s) for s in split(lhs, ",")], collect(Char, rhs))
end

struct Step
    abs_i::Int
    abs_j::Int
    code::DynamicEinCode{Char}
end

"""Turn the corpus's positional pair path into nested pairwise contractions."""
function build_plan(n_inputs::Int, path::Vector{Vector{Int}},
                    operand_labels::Vector{Vector{Char}}, output_labels::Vector{Char})
    available = collect(0:(n_inputs - 1))
    label_sets = Dict{Int,Vector{Char}}()
    for i in 0:(n_inputs - 1)
        label_sets[i] = operand_labels[i + 1]
    end

    nsteps = length(path)
    steps = Vector{Step}(undef, nsteps)
    for (step_idx, pair) in enumerate(path)
        a, b = pair[1], pair[2]
        i, j = a < b ? (a, b) : (b, a)
        abs_i, abs_j = available[i + 1], available[j + 1]
        deleteat!(available, j + 1)
        deleteat!(available, i + 1)

        ix_i = label_sets[abs_i]
        ix_j = label_sets[abs_j]
        is_final = step_idx == nsteps
        iy = if is_final
            output_labels
        else
            remaining = Set{Char}()
            for id in available
                union!(remaining, label_sets[id])
            end
            union!(remaining, output_labels)
            seen = Char[]
            for c in Iterators.flatten((ix_i, ix_j))
                if (c in remaining) && !(c in seen)
                    push!(seen, c)
                end
            end
            seen
        end
        steps[step_idx] = Step(abs_i, abs_j, DynamicEinCode([copy(ix_i), copy(ix_j)], iy))
        label_sets[n_inputs + step_idx - 1] = iy
        push!(available, n_inputs + step_idx - 1)
    end
    steps
end

function run_plan(steps::Vector{Step}, operands::Vector{<:AbstractArray{Float64}})
    tensors = Vector{Any}(undef, length(operands) + length(steps))
    for (k, op) in enumerate(operands)
        tensors[k] = op
    end
    local result = operands[1]
    for (k, step) in enumerate(steps)
        result = step.code(tensors[step.abs_i + 1], tensors[step.abs_j + 1])
        tensors[length(operands) + k] = result
    end
    result
end

"""The four cross-arm values, measured in row-major order like the Rust side."""
function diagnostics(out::AbstractArray{Float64})
    strides = row_major_strides(collect(Int, size(out)))
    s = 0.0; sq = 0.0; mx = 0.0; wr = 0.0
    for I in CartesianIndices(out)
        lin = 0
        @inbounds for k in eachindex(strides)
            lin += (I[k] - 1) * strides[k]
        end
        x = out[I]
        s += x; sq += x * x; mx = max(mx, abs(x)); wr += weight(lin) * x
    end
    (s, 0.0, sq, mx, wr, 0.0)
end

"""Median of the samples, the statistic the timing policy declares."""
median_of(xs::Vector{Float64}) = begin
    s = sort(xs); n = length(s)
    isodd(n) ? s[(n + 1) ÷ 2] : 0.5 * (s[n ÷ 2] + s[n ÷ 2 + 1])
end

"""Run `f` until `prime_ms`, then `reps` timed calls; sample SD of the timed calls."""
function timed(reps::Int, prime_ms::Int, f)
    if prime_ms > 0
        deadline = time() + prime_ms / 1000
        while time() < deadline
            f()
        end
    end
    samples = Float64[]
    for _ in 1:reps
        t0 = time_ns()
        f()
        push!(samples, (time_ns() - t0) / 1e6)
    end
    samples
end

function argval(argv, flag, default = nothing)
    i = findfirst(==(flag), argv)
    i === nothing ? default : argv[i + 1]
end

function main(argv)
    instances_dir = argval(argv, "--instances")
    instances_dir === nothing && error("--instances DIR is required")
    strategy = argval(argv, "--strategy", "opt_size")
    threads = parse(Int, argval(argv, "--threads", "1"))
    reps = parse(Int, argval(argv, "--reps", "5"))
    prime_ms = parse(Int, argval(argv, "--prime-ms", "250"))
    csv = argval(argv, "--csv")
    diag_csv = argval(argv, "--diagnostics-csv")
    regime = argval(argv, "--regime", "cpueinsum")

    Threads.nthreads() == threads ||
        @warn "Julia runs $(Threads.nthreads()) threads, the campaign declares $threads"

    timing = IOBuffer()
    diags = IOBuffer()
    print(timing, "regime,family,dtype,order,m,n,k,batch,row,threads,status,note,total_ms,per_item_us,samples_ms,rayon_threads,vendor_threads,case_m,case_n,case_k\n")
    print(diags, "regime,family,dtype,m,n,k,batch,row,sum_re,sum_im,sum_sq,max_abs,weighted_re,weighted_im,status\n")

    files = sort(filter(f -> endswith(f, ".json"), readdir(instances_dir; join = true)))
    for file in files
        d = JSON.parsefile(file)
        format = get(d, "format_string", nothing)
        format === nothing && continue
        shapes = [Vector{Int}(s) for s in d["shapes"]]
        paths = d["paths"]
        haskey(paths, strategy) || continue
        path = [Vector{Int}(p) for p in paths[strategy]["path"]]
        dtype = String(d["dtype"])
        dtype == "float64" || continue

        (operand_labels, output_labels) = parse_format(format)
        length(operand_labels) == length(shapes) ||
            error("$(d["name"]): the format string names $(length(operand_labels)) operands, the file declares $(length(shapes))")

        operands = [operand(sh) for sh in shapes]
        steps = build_plan(length(operands), path, operand_labels, output_labels)

        local result
        samples = timed(reps, prime_ms, () -> (result = run_plan(steps, operands)))
        dg = diagnostics(result)
        med = median_of(samples)
        m = sum(samples) / length(samples)
        sd = length(samples) > 1 ? sqrt(sum((samples .- m) .^ 2) / (length(samples) - 1)) : 0.0
        total = med
        per_item = total * 1000.0
        input_len = sum(prod(sh) for sh in shapes)
        @printf(timing,
            "%s,%s,%s,,1,1,,1,%s,%d,ok,,%.9f,%.9f,[%s],%d,0,%d,%d,%d\n",
            regime, d["name"], dtype, strategy, threads, total, per_item,
            join((@sprintf("%.12f", x) for x in samples), ","), threads,
            length(shapes), input_len, length(result))
        @printf(diags, "%s,%s,%s,1,1,,1,%s,%.17e,%.17e,%.17e,%.17e,%.17e,%.17e,ok\n",
            regime, d["name"], dtype, strategy, dg[1], dg[2], dg[3], dg[4], dg[5], dg[6])
        println(stderr, "ok $(d["name"]) $(strategy) $(round(med; digits = 4)) ms (sd $(round(sd; digits = 4)))")
    end

    csv === nothing || write(csv, String(take!(timing)))
    diag_csv === nothing || write(diag_csv, String(take!(diags)))
end

main(ARGS)

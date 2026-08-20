#!/usr/bin/env python3
"""
OmniVoice Benchmark — latency, RTF, memory over N runs.

Usage:
    python benchmarks/run_benchmark.py --device mps --num-step 16 --runs 100

After running, results/ folder contains:
    <device>_step<N>.csv    raw data
    report.md               markdown summary table

Upstream Discussion post template (after running):
    Post to: https://github.com/k2-fsa/OmniVoice/discussions
    Title: "Benchmark results: Apple Silicon MPS performance"
    Body: paste contents of report.md
"""
from __future__ import annotations

import argparse
import csv
import gc
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# ── Test cases ────────────────────────────────────────────────────────────────

TEST_CASES = {
    "short_auto": {
        "text": "Hello, world. This is a test.",
        "mode": "auto",
    },
    "medium_auto": {
        "text": "The quick brown fox jumps over the lazy dog. " * 4,
        "mode": "auto",
    },
    "long_auto": {
        "text": "In the beginning was the word. " * 15,
        "mode": "auto",
    },
    "short_design": {
        "text": "Hello, this is voice design.",
        "mode": "design",
        "instruct": "female, british accent",
    },
    "medium_clone": {
        "text": "Hello, this is a voice clone test.",
        "mode": "clone",
        "ref_audio": str(Path(__file__).parent / "sample_ref.wav"),
    },
}

SAMPLE_RATE = 24_000


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RunResult:
    device: str
    num_step: int
    test_case: str
    mode: str
    run_index: int
    latency_ms: float
    audio_duration_ms: float
    rtf: float
    ram_before_mb: float
    ram_after_mb: float
    ram_delta_mb: float
    cuda_allocated_before_mb: float | None
    cuda_allocated_after_mb: float | None
    cuda_peak_allocated_mb: float | None
    cuda_reserved_before_mb: float | None
    cuda_reserved_after_mb: float | None
    cuda_peak_reserved_mb: float | None
    startup_allocated_mb: float | None
    startup_reserved_mb: float | None
    startup_peak_allocated_mb: float | None
    startup_peak_reserved_mb: float | None
    audio_tokenizer_parameter_mb: float | None
    error: str | None = None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="mps",
                        choices=["mps", "cpu", "cuda"],
                        help="Inference device")
    parser.add_argument("--num-step", type=int, default=16,
                        help="Diffusion steps")
    parser.add_argument("--runs", type=int, default=100,
                        help="Iterations per test case (for memory leak detection)")
    parser.add_argument("--warmup", type=int, default=1,
                        help="Warm-up runs (not counted)")
    parser.add_argument(
        "--ref-text",
        default=None,
        help=(
            "Reference transcript for clone cases; avoids loading the ASR "
            "pipeline and its TorchCodec dependency"
        ),
    )
    parser.add_argument(
        "--ref-audio",
        default=None,
        help=(
            "Speech reference WAV for clone cases; overrides the bundled test-tone "
            "fixture"
        ),
    )
    parser.add_argument("--cases", nargs="+", default=list(TEST_CASES.keys()),
                        help="Test cases to run")
    parser.add_argument("--output-dir", default="benchmarks/results",
                        help="Directory for CSV and report outputs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    import psutil
    import torch
    from omnivoice import OmniVoice

    # Load model
    print(f"Loading model on device={args.device}...")
    dtype = torch.float16 if args.device != "cpu" else torch.float32
    device_map = "cuda:0" if args.device == "cuda" else args.device

    t0 = time.monotonic()
    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map=device_map,
        dtype=dtype,
    )
    print(f"Model loaded in {time.monotonic() - t0:.1f}s")

    cuda_enabled = args.device == "cuda" and torch.cuda.is_available()

    def sync_cuda() -> None:
        if cuda_enabled:
            torch.cuda.synchronize()

    def cuda_memory() -> tuple[float | None, float | None]:
        if not cuda_enabled:
            return None, None
        return (
            torch.cuda.memory_allocated() / 1024 / 1024,
            torch.cuda.memory_reserved() / 1024 / 1024,
        )

    def module_parameter_memory(module) -> float | None:
        if module is None:
            return None
        return sum(p.numel() * p.element_size() for p in module.parameters()) / 1024 / 1024

    sync_cuda()
    startup_allocated, startup_reserved = cuda_memory()
    if cuda_enabled:
        startup_peak_allocated = torch.cuda.max_memory_allocated() / 1024 / 1024
        startup_peak_reserved = torch.cuda.max_memory_reserved() / 1024 / 1024
    else:
        startup_peak_allocated = startup_peak_reserved = None
    tokenizer_parameter_mb = module_parameter_memory(getattr(model, "audio_tokenizer", None))
    print(
        "Startup VRAM: "
        f"allocated={startup_allocated or 0:.1f} MB, "
        f"reserved={startup_reserved or 0:.1f} MB, "
        f"audio-tokenizer parameters={tokenizer_parameter_mb or 0:.1f} MB"
    )

    def get_ram() -> float:
        return psutil.Process().memory_info().rss / 1024 / 1024

    def run_once(case: dict) -> tuple[list, float]:
        kwargs = {"text": case["text"], "num_step": args.num_step}
        if case["mode"] == "design":
            kwargs["instruct"] = case["instruct"]
        elif case["mode"] == "clone":
            ref_audio = args.ref_audio or case["ref_audio"]
            if not Path(ref_audio).exists():
                raise FileNotFoundError(
                    f"Reference audio not found at {ref_audio}. "
                    "Provide a 5–10s speech WAV with --ref-audio."
                )
            kwargs["ref_audio"] = ref_audio
            if args.ref_text:
                kwargs["ref_text"] = args.ref_text
        tensors = model.generate(**kwargs)
        duration_s = sum(t.shape[-1] for t in tensors) / SAMPLE_RATE
        return tensors, duration_s

    def cleanup() -> None:
        gc.collect()
        if args.device == "mps":
            try:
                torch.mps.empty_cache()
            except Exception:
                pass
        elif args.device == "cuda":
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    all_results: list[RunResult] = []

    for case_name in args.cases:
        if case_name not in TEST_CASES:
            print(f"  [SKIP] Unknown case '{case_name}'")
            continue

        case = TEST_CASES[case_name]
        print(f"\n── {case_name} (mode={case['mode']}) ──────────────")

        # Warm-up
        for _ in range(args.warmup):
            try:
                run_once(case)
            except Exception as e:
                print(f"  [WARN] Warm-up failed: {e}")
            cleanup()

        # Benchmark
        for i in range(args.runs):
            ram_before = get_ram()
            if cuda_enabled:
                torch.cuda.reset_peak_memory_stats()
            sync_cuda()
            cuda_allocated_before, cuda_reserved_before = cuda_memory()
            t_start = time.perf_counter()
            error = None
            duration_ms = 0.0

            try:
                _, duration_s = run_once(case)
                latency_ms = (time.perf_counter() - t_start) * 1000
                duration_ms = duration_s * 1000
            except Exception as e:
                latency_ms = -1
                error = str(e)

            sync_cuda()
            cuda_allocated_after, cuda_reserved_after = cuda_memory()
            if cuda_enabled:
                cuda_peak_allocated = torch.cuda.max_memory_allocated() / 1024 / 1024
                cuda_peak_reserved = torch.cuda.max_memory_reserved() / 1024 / 1024
            else:
                cuda_peak_allocated = cuda_peak_reserved = None
            cleanup()
            ram_after = get_ram()
            rtf = (latency_ms / 1000) / (duration_ms / 1000) if duration_ms > 0 else -1

            result = RunResult(
                device=args.device,
                num_step=args.num_step,
                test_case=case_name,
                mode=case["mode"],
                run_index=i,
                latency_ms=round(latency_ms, 1),
                audio_duration_ms=round(duration_ms, 1),
                rtf=round(rtf, 4),
                ram_before_mb=round(ram_before, 1),
                ram_after_mb=round(ram_after, 1),
                ram_delta_mb=round(ram_after - ram_before, 1),
                cuda_allocated_before_mb=_round_optional(cuda_allocated_before),
                cuda_allocated_after_mb=_round_optional(cuda_allocated_after),
                cuda_peak_allocated_mb=_round_optional(cuda_peak_allocated),
                cuda_reserved_before_mb=_round_optional(cuda_reserved_before),
                cuda_reserved_after_mb=_round_optional(cuda_reserved_after),
                cuda_peak_reserved_mb=_round_optional(cuda_peak_reserved),
                startup_allocated_mb=_round_optional(startup_allocated),
                startup_reserved_mb=_round_optional(startup_reserved),
                startup_peak_allocated_mb=_round_optional(startup_peak_allocated),
                startup_peak_reserved_mb=_round_optional(startup_peak_reserved),
                audio_tokenizer_parameter_mb=_round_optional(tokenizer_parameter_mb),
                error=error,
            )
            all_results.append(result)

            if i % 10 == 0:
                status = f"run {i:3d}: lat={latency_ms:.0f}ms  rtf={rtf:.3f}  " \
                         f"ram_Δ={result.ram_delta_mb:+.1f}MB  ram={ram_after:.0f}MB"
                if cuda_enabled:
                    status += f"  vram_peak={result.cuda_peak_allocated_mb:.0f}MB"
                if error:
                    status += f"  ERR={error[:40]}"
                print(f"  {status}")

    # Write CSV
    csv_path = output_dir / f"{args.device}_step{args.num_step}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(all_results[0]).keys()))
        writer.writeheader()
        for r in all_results:
            writer.writerow(asdict(r))
    print(f"\n✓ CSV → {csv_path}")

    # Generate report
    report_path = output_dir / "report.md"
    _write_report(all_results, report_path, args)
    print(f"✓ Report → {report_path}")
    print(f"\nUpstream Discussion post: paste {report_path} to")
    print("  https://github.com/k2-fsa/OmniVoice/discussions")


def _round_optional(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _write_report(results: list[RunResult], path: Path, args) -> None:
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for r in results:
        if r.error is None:
            groups[(r.device, r.num_step, r.test_case)].append(r)

    lines = [
        "# OmniVoice Benchmark Results\n\n",
        f"Device: `{args.device}` | Steps: `{args.num_step}` | "
        f"Runs per case: `{args.runs}`\n\n",
        "## Latency & RTF\n\n",
        "| Device | Steps | Test Case | Mean (ms) | p95 (ms) | Mean RTF | Errors |\n",
        "|--------|-------|-----------|-----------|----------|----------|--------|\n",
    ]

    for (device, steps, case), rs in sorted(groups.items()):
        lats = [r.latency_ms for r in rs]
        rtfs = [r.rtf for r in rs if r.rtf > 0]
        errors = sum(1 for r in results
                     if r.test_case == case and r.error is not None)
        p95 = sorted(lats)[int(len(lats) * 0.95)] if lats else 0
        mean_lat = statistics.mean(lats) if lats else 0
        mean_rtf = statistics.mean(rtfs) if rtfs else 0
        lines.append(
            f"| {device} | {steps} | {case} | "
            f"{mean_lat:.0f} | {p95:.0f} | {mean_rtf:.4f} | {errors} |\n"
        )

    lines += [
        "\n## Memory (RAM across all runs)\n\n",
        "| Test Case | Initial RAM (MB) | Final RAM (MB) | Total Δ (MB) | Leak? |\n",
        "|-----------|-----------------|----------------|--------------|-------|\n",
    ]

    for (_, _, case), rs in sorted(groups.items()):
        if not rs:
            continue
        initial = rs[0].ram_before_mb
        final = rs[-1].ram_after_mb
        delta = final - initial
        leak = "⚠️ YES" if delta > 200 else "✅ NO"
        lines.append(
            f"| {case} | {initial:.0f} | {final:.0f} | "
            f"{delta:+.0f} | {leak} |\n"
        )

    lines += [
        "\n## Interpretation\n\n",
        "- **RTF < 1.0** = faster than real-time (good)\n",
        "- **RTF > 1.0** = slower than real-time (server usable but audio chunks will lag)\n",
        "- **RAM Δ > 200MB** across 100 runs = memory leak detected\n",
    ]

    first = results[0] if results else None
    if first and first.cuda_peak_allocated_mb is not None:
        lines += [
            "\n## CUDA VRAM\n\n",
            f"- Startup allocated: **{first.startup_allocated_mb:.1f} MB**\n",
            f"- Startup reserved: **{first.startup_reserved_mb:.1f} MB**\n",
            f"- Startup peak allocated: **{first.startup_peak_allocated_mb:.1f} MB**\n",
            f"- Startup peak reserved: **{first.startup_peak_reserved_mb:.1f} MB**\n",
            "- Static audio-tokenizer parameters: "
            f"**{first.audio_tokenizer_parameter_mb:.1f} MB**\n",
            "\n| Test Case | Peak Allocated (MB) | Peak Reserved (MB) |\n",
            "|-----------|---------------------|--------------------|\n",
        ]
        for (_, _, case), rs in sorted(groups.items()):
            peak_allocated = max(r.cuda_peak_allocated_mb for r in rs)
            peak_reserved = max(r.cuda_peak_reserved_mb for r in rs)
            lines.append(f"| {case} | {peak_allocated:.1f} | {peak_reserved:.1f} |\n")

    lines += [
        "\n*Generated by omnivoice-server benchmark harness*\n",
    ]

    path.write_text("".join(lines))


if __name__ == "__main__":
    main()

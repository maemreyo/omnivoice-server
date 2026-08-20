#!/usr/bin/env python3
"""
Sample QA matrix for omnivoice-server upstream alignment.

Covers every new feature area:
  A. Baseline (no new params, preset / instructions / default)
  B. New generation params (layer_penalty_factor, preprocess_prompt,
     postprocess_output, audio_chunk_duration, audio_chunk_threshold)
  C. Instruction validation (valid canonical, accent aliases, invalid rejection)
  D. Non-verbal / pronunciation pass-through
  E. Clone endpoint parity  (skipped if no --ref-audio provided)
  F. /v1/voices metadata inspection

Usage:
  python3 scripts/generate_qa_samples.py
  python3 scripts/generate_qa_samples.py --base-url http://127.0.0.1:8880
  python3 scripts/generate_qa_samples.py --ref-audio /path/to/ref.wav

Outputs go to  samples/qa/<id>_<label>.wav
A JSON report   samples/qa/report.json  is written at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Sample text fixtures
# ---------------------------------------------------------------------------
TEXT_SHORT = "The quick brown fox jumps over the lazy dog."
TEXT_MEDIUM = (
    "Welcome to OmniVoice server. This is a text-to-speech system that supports "
    "multiple voices, languages, and fine-grained generation controls."
)
TEXT_NONVERBAL = (
    "Hello! [laughter] How are you? [breath] I am doing great. [sigh] "
    "Let me tell you something interesting. [sniff] Ready?"
)
TEXT_PRONUNCIATION_EN = (
    "The word {k ae1 t} is easy to pronounce. The word {s t r eh1 ng th} is harder."
)
TEXT_PRONUNCIATION_ZH = (
    "\u4eca\u5929\u5929\u6c14\u5f88\u597d\u3002{ni3 hao3}\uff0c\u4f60\u597d\u5417\uff1f"
)
TEXT_LONG = ("This is a chunking verification sample. " * 4).strip()


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------
def build_cases(ref_audio_path: str | None) -> list[dict]:
    cases: list[dict] = []

    # -------------------------------------------------- A. Baseline
    cases += [
        {
            "id": "A01",
            "group": "baseline",
            "label": "default_no_params",
            "desc": "Server defaults, no instructions",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT},
            "expect_status": 200,
        },
        {
            "id": "A02",
            "group": "baseline",
            "label": "preset_alloy",
            "desc": "OpenAI preset 'alloy'",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "voice": "alloy"},
            "expect_status": 200,
        },
        {
            "id": "A03",
            "group": "baseline",
            "label": "preset_nova",
            "desc": "OpenAI preset 'nova'",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "voice": "nova"},
            "expect_status": 200,
        },
        {
            "id": "A04",
            "group": "baseline",
            "label": "instructions_female_british",
            "desc": "Canonical instructions: female, british accent",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "female,british accent"},
            "expect_status": 200,
        },
        {
            "id": "A05",
            "group": "baseline",
            "label": "instructions_male_low_pitch",
            "desc": "Canonical instructions: male, low pitch",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "male,low pitch"},
            "expect_status": 200,
        },
    ]

    # -------------------------------------------------- B. New generation params
    cases += [
        {
            "id": "B01",
            "group": "new_params",
            "label": "layer_penalty_factor_default",
            "desc": "layer_penalty_factor=5.0 (upstream default value)",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "layer_penalty_factor": 5.0},
            "expect_status": 200,
        },
        {
            "id": "B02",
            "group": "new_params",
            "label": "layer_penalty_factor_low",
            "desc": "layer_penalty_factor=1.0 (low penalty)",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "layer_penalty_factor": 1.0},
            "expect_status": 200,
        },
        {
            "id": "B03",
            "group": "new_params",
            "label": "layer_penalty_factor_high",
            "desc": "layer_penalty_factor=10.0 (high penalty)",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "layer_penalty_factor": 10.0},
            "expect_status": 200,
        },
        {
            "id": "B04",
            "group": "new_params",
            "label": "preprocess_prompt_true",
            "desc": "preprocess_prompt=True",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "preprocess_prompt": True},
            "expect_status": 200,
        },
        {
            "id": "B05",
            "group": "new_params",
            "label": "preprocess_prompt_false",
            "desc": "preprocess_prompt=False",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "preprocess_prompt": False},
            "expect_status": 200,
        },
        {
            "id": "B06",
            "group": "new_params",
            "label": "postprocess_output_true",
            "desc": "postprocess_output=True (removes trailing silence)",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "postprocess_output": True},
            "expect_status": 200,
        },
        {
            "id": "B07",
            "group": "new_params",
            "label": "postprocess_output_false",
            "desc": "postprocess_output=False",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "postprocess_output": False},
            "expect_status": 200,
        },
        {
            "id": "B08",
            "group": "new_params",
            "label": "audio_chunk_on_long_text",
            "desc": "chunked generation path on moderate text with low threshold",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {
                "input": TEXT_LONG,
                "num_step": 4,
                "audio_chunk_duration": 1.0,
                "audio_chunk_threshold": 0.1,
                "request_timeout_s": 120,
            },
            "expect_status": 200,
            "timeout_override": 120,
        },
        {
            "id": "B09",
            "group": "new_params",
            "label": "all_new_params_combined",
            "desc": "All 5 new params together on medium text",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {
                "input": TEXT_MEDIUM,
                "layer_penalty_factor": 5.0,
                "preprocess_prompt": True,
                "postprocess_output": True,
                "audio_chunk_duration": 15.0,
                "audio_chunk_threshold": 30.0,
            },
            "expect_status": 200,
        },
        # Invalid -- expect 422
        {
            "id": "B10",
            "group": "new_params_invalid",
            "label": "layer_penalty_negative_REJECT",
            "desc": "layer_penalty_factor=-1.0 -> must return 422",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "layer_penalty_factor": -1.0},
            "expect_status": 422,
            "no_save": True,
        },
        {
            "id": "B11",
            "group": "new_params_invalid",
            "label": "audio_chunk_zero_REJECT",
            "desc": "audio_chunk_duration=0.0 -> must return 422",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "audio_chunk_duration": 0.0},
            "expect_status": 422,
            "no_save": True,
        },
    ]

    # -------------------------------------------------- C. Instruction validation
    cases += [
        {
            "id": "C01",
            "group": "instructions_valid",
            "label": "alias_british",
            "desc": "Accent alias 'british' -> canonicalized to 'british accent'",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "british"},
            "expect_status": 200,
        },
        {
            "id": "C02",
            "group": "instructions_valid",
            "label": "alias_american",
            "desc": "Accent alias 'american' -> canonicalized to 'american accent'",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "american"},
            "expect_status": 200,
        },
        {
            "id": "C03",
            "group": "instructions_valid",
            "label": "young_female_high_pitch",
            "desc": "Valid combination: young adult, female, high pitch",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "young adult,female,high pitch"},
            "expect_status": 200,
        },
        {
            "id": "C04",
            "group": "instructions_valid",
            "label": "whisper_style",
            "desc": "Whisper style",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "whisper"},
            "expect_status": 200,
        },
        {
            "id": "C05",
            "group": "instructions_valid",
            "label": "full_canonical_design",
            "desc": (
                "Full canonical instructions: male, middle-aged, moderate pitch, british accent"
            ),
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {
                "input": TEXT_SHORT,
                "instructions": "male,middle-aged,moderate pitch,british accent",
            },
            "expect_status": 200,
        },
        # Invalid
        {
            "id": "C06",
            "group": "instructions_invalid",
            "label": "cheerful_REJECT",
            "desc": "Unsupported emotion 'cheerful' -> must return 422",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "cheerful"},
            "expect_status": 422,
            "no_save": True,
        },
        {
            "id": "C07",
            "group": "instructions_invalid",
            "label": "customer_service_REJECT",
            "desc": "Unsupported style 'customer_service' -> must return 422",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "customer_service"},
            "expect_status": 422,
            "no_save": True,
        },
        {
            "id": "C08",
            "group": "instructions_invalid",
            "label": "gender_conflict_REJECT",
            "desc": "Conflicting gender 'male,female' -> must return 422",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": "male,female"},
            "expect_status": 422,
            "no_save": True,
        },
        {
            "id": "C09",
            "group": "instructions_invalid",
            "label": "empty_REJECT",
            "desc": "Empty instructions string -> must return 422",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_SHORT, "instructions": ""},
            "expect_status": 422,
            "no_save": True,
        },
    ]

    # -------------------------------------------------- D. Non-verbal / pronunciation
    cases += [
        {
            "id": "D01",
            "group": "nonverbal",
            "label": "nonverbal_tags",
            "desc": "Non-verbal tags: [laughter], [breath], [sigh], [sniff]",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_NONVERBAL},
            "expect_status": 200,
        },
        {
            "id": "D02",
            "group": "pronunciation",
            "label": "english_cmu",
            "desc": "English CMU pronunciation hints inline in text",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_PRONUNCIATION_EN, "instructions": "male,american accent"},
            "expect_status": 200,
        },
        {
            "id": "D03",
            "group": "pronunciation",
            "label": "chinese_pinyin",
            "desc": "Chinese pinyin pronunciation hints inline in text",
            "endpoint": "/v1/audio/speech",
            "method": "json",
            "body": {"input": TEXT_PRONUNCIATION_ZH},
            "expect_status": 200,
        },
    ]

    # -------------------------------------------------- E. Script endpoint cases
    cases += [
        {
            "id": "E01",
            "group": "script",
            "label": "script_single_track",
            "desc": "Script endpoint: single_track output (default)",
            "endpoint": "/v1/audio/script",
            "method": "json",
            "body": {
                "script": [
                    {"speaker": "alice", "text": "Hello world"},
                    {"speaker": "bob", "text": "Hi there"},
                ],
                "default_voice": "female, british accent",
            },
            "expect_status": 200,
        },
        {
            "id": "E02",
            "group": "script",
            "label": "script_multi_track",
            "desc": "Script endpoint: multi_track output with metadata",
            "endpoint": "/v1/audio/script",
            "method": "json",
            "body": {
                "script": [
                    {"speaker": "alice", "text": "Hello world"},
                    {"speaker": "bob", "text": "Hi there"},
                ],
                "output_format": "multi_track",
                "default_voice": "female, british accent",
            },
            "expect_status": 200,
        },
        {
            "id": "E03",
            "group": "script",
            "label": "script_with_speed_override",
            "desc": "Script endpoint: per-segment speed override",
            "endpoint": "/v1/audio/script",
            "method": "json",
            "body": {
                "script": [
                    {"speaker": "alice", "text": "Fast speech", "speed": 1.5},
                    {"speaker": "bob", "text": "Slow speech", "speed": 0.8},
                ],
                "default_voice": "female, british accent",
            },
            "expect_status": 200,
        },
        {
            "id": "E04",
            "group": "script",
            "label": "script_with_voice_override",
            "desc": "Script endpoint: per-segment voice override",
            "endpoint": "/v1/audio/script",
            "method": "json",
            "body": {
                "script": [
                    {
                        "speaker": "alice",
                        "text": "British accent",
                        "voice": "female,british accent",
                    },
                    {"speaker": "bob", "text": "American accent", "voice": "male,american accent"},
                ],
                "default_voice": "female, british accent",
            },
            "expect_status": 200,
        },
        {
            "id": "E05",
            "group": "script",
            "label": "script_with_pause",
            "desc": "Script endpoint: custom pause between speakers",
            "endpoint": "/v1/audio/script",
            "method": "json",
            "body": {
                "script": [
                    {"speaker": "alice", "text": "First line"},
                    {"speaker": "bob", "text": "Second line"},
                ],
                "pause_between_speakers": 1.0,
                "default_voice": "female, british accent",
            },
            "expect_status": 200,
        },
    ]

    # -------------------------------------------------- F. Clone parity
    if ref_audio_path:
        cases += [
            {
                "id": "F01",
                "group": "clone_parity",
                "label": "clone_basic",
                "desc": "Clone basic request",
                "endpoint": "/v1/audio/speech/clone",
                "method": "multipart",
                "fields": {"input": TEXT_SHORT},
                "file_field": "ref_audio",
                "file_path": ref_audio_path,
                "expect_status": 200,
            },
            {
                "id": "F02",
                "group": "clone_parity",
                "label": "clone_all_new_params",
                "desc": "Clone with all 5 new params",
                "endpoint": "/v1/audio/speech/clone",
                "method": "multipart",
                "fields": {
                    "input": TEXT_SHORT,
                    "layer_penalty_factor": "5.0",
                    "preprocess_prompt": "true",
                    "postprocess_output": "true",
                    "audio_chunk_duration": "15.0",
                    "audio_chunk_threshold": "30.0",
                },
                "file_field": "ref_audio",
                "file_path": ref_audio_path,
                "expect_status": 200,
            },
            {
                "id": "F03",
                "group": "clone_parity_invalid",
                "label": "clone_neg_penalty_REJECT",
                "desc": "Clone layer_penalty_factor=-1.0 -> must return 422",
                "endpoint": "/v1/audio/speech/clone",
                "method": "multipart",
                "fields": {"input": TEXT_SHORT, "layer_penalty_factor": "-1.0"},
                "file_field": "ref_audio",
                "file_path": ref_audio_path,
                "expect_status": 422,
                "no_save": True,
            },
        ]
    else:
        print("[INFO] No --ref-audio provided. Skipping clone endpoint cases (F01-F03).")

    return cases


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------
def run_case(case: dict, base_url: str, out_dir: Path, timeout: int = 120) -> dict:
    url = base_url.rstrip("/") + case["endpoint"]
    expect = case.get("expect_status", 200)
    no_save = case.get("no_save", False)
    effective_timeout = case.get("timeout_override", timeout)

    t0 = time.monotonic()
    try:
        if case["method"] == "json":
            resp = requests.post(url, json=case["body"], timeout=effective_timeout)
        elif case["method"] == "multipart":
            file_path = Path(case["file_path"])
            with open(file_path, "rb") as fh:
                files = {case["file_field"]: (file_path.name, fh, "audio/wav")}
                data = {k: str(v) for k, v in case["fields"].items()}
                resp = requests.post(url, data=data, files=files, timeout=effective_timeout)
        else:
            raise ValueError(f"Unknown method: {case['method']}")
    except Exception as exc:
        return {
            "id": case["id"],
            "label": case["label"],
            "group": case["group"],
            "desc": case["desc"],
            "status": "ERROR",
            "error": str(exc),
            "latency_s": round(time.monotonic() - t0, 2),
        }

    latency = round(time.monotonic() - t0, 2)
    passed = resp.status_code == expect

    saved_path = None
    if not no_save and resp.status_code == 200:
        content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        suffix = ".json" if content_type == "application/json" else ".wav"
        filename = f"{case['id']}_{case['label']}{suffix}"
        saved_path = str(out_dir / filename)
        with open(saved_path, "wb") as f:
            f.write(resp.content)

    result: dict = {
        "id": case["id"],
        "label": case["label"],
        "group": case["group"],
        "desc": case["desc"],
        "endpoint": case["endpoint"],
        "status": "PASS" if passed else "FAIL",
        "expect_status": expect,
        "actual_status": resp.status_code,
        "latency_s": latency,
        "saved_path": saved_path,
    }
    if not passed:
        try:
            result["error_body"] = resp.json()
        except Exception:
            result["error_body"] = resp.text[:500]
    return result


def run_voices_check(base_url: str) -> dict:
    """Check /v1/voices response shape.

    Expected shape:
        {"voices": [...], "design_attributes": {...}, "total": N}
    """
    url = base_url.rstrip("/") + "/v1/voices"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        is_list = isinstance(data.get("voices"), list)
        has_design_attrs = isinstance(data.get("design_attributes"), dict) and bool(
            data["design_attributes"]
        )
        all_attr_keys = set(data.get("design_attributes", {}).keys())
        forbidden = {"emotion", "speaking_style"}
        contaminated = list(forbidden & all_attr_keys)
        ok = is_list and has_design_attrs and not contaminated
        return {
            "id": "G01",
            "label": "voices_metadata",
            "group": "metadata",
            "desc": "GET /v1/voices: canonical attrs, no unsupported categories",
            "endpoint": "/v1/voices",
            "actual_status": resp.status_code,
            "status": "PASS" if ok else "FAIL",
            "has_list": is_list,
            "has_design_attrs": has_design_attrs,
            "contaminated_categories": contaminated,
        }
    except Exception as exc:
        return {
            "id": "G01",
            "label": "voices_metadata",
            "group": "metadata",
            "status": "ERROR",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="OmniVoice sample QA matrix")
    parser.add_argument("--base-url", default="http://127.0.0.1:8880")
    parser.add_argument("--ref-audio", default=None, help="Path to ref WAV for clone tests")
    parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout seconds")
    parser.add_argument("--out-dir", default="samples/qa")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        h = requests.get(args.base_url + "/health", timeout=5)
        print(f"[OK] Server healthy: {h.json()}")
    except Exception as exc:
        print(f"[ERROR] Server unreachable at {args.base_url}: {exc}")
        sys.exit(1)

    cases = build_cases(args.ref_audio)
    results: list[dict] = []

    print(f"\nRunning {len(cases)} sample QA cases...")
    print("-" * 70)

    for case in cases:
        icon = "\U0001f50a" if not case.get("no_save") else "\U0001f6ab"
        print(f"{icon}  [{case['id']}] {case['desc']}...", end=" ", flush=True)
        result = run_case(case, args.base_url, out_dir, timeout=args.timeout)
        results.append(result)
        emoji = "\u2705" if result["status"] == "PASS" else "\u274c"
        status_info = f"{result.get('actual_status')} in {result.get('latency_s', '?')}s"
        print(f"{emoji} {result['status']}  ({status_info})")
        if result["status"] != "PASS":
            print(f"    >> {result.get('error_body', result.get('error', 'unknown'))}")

    print("\n[G01] GET /v1/voices metadata...", end=" ", flush=True)
    vr = run_voices_check(args.base_url)
    results.append(vr)
    vr_icon = "✅" if vr["status"] == "PASS" else "❌"
    print(f"{vr_icon} {vr['status']}")
    if vr["status"] != "PASS":
        print(f"    >> {vr}")

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    total = len(results)

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed}/{total} passed  |  {failed} failed  |  {errors} errors")

    groups: dict[str, list] = defaultdict(list)
    for r in results:
        groups[r["group"]].append(r)
    print("\nGroup breakdown:")
    for grp, grp_results in sorted(groups.items()):
        gp = sum(1 for r in grp_results if r["status"] == "PASS")
        print(f"  {grp:42s} {gp}/{len(grp_results)} pass")

    saved = [r["saved_path"] for r in results if r.get("saved_path")]
    print(f"\nAudio samples saved: {len(saved)} files in {out_dir}/")
    for p in sorted(saved):
        sz = Path(p).stat().st_size // 1024
        print(f"  {Path(p).name}  ({sz} KB)")

    report_path = out_dir / "report.json"
    with open(report_path, "w") as f:
        json.dump(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "base_url": args.base_url,
                "total": total,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"\nReport written to {report_path}")

    if failed or errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

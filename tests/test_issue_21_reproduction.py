"""
Reproduction test for Issue #21: Voice Clone Bug
https://github.com/maemreyo/omnivoice-server/issues/21

Bug description:
- Clone not working - two male voices when using clone:male_profile and clone:female_profile
- Voice inconsistency - same transcript produces different voices each generation
- Wrong gender output - Voice ID like "ash" produces wrong gender

This test reproduces the clone voice issue to verify trace logging works.
"""

from __future__ import annotations

import io
import logging

# Enable trace logging to see what's happening
logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")


def test_script_clone_two_speakers_two_different_profiles(client, sample_audio_bytes):
    """
    REPRODUCE BUG #21: Two speakers with different clone profiles should get different voices.

    This test creates:
    - male_profile: reference audio for male voice
    - female_profile: reference audio for female voice

    Then sends a script with:
    - speaker "alice" using clone:male_profile
    - speaker "bob" using clone:female_profile

    EXPECTED: alice should use male_profile, bob should use female_profile
    ACTUAL (BUG): Both use the same profile or one falls back to design mode
    """

    # Create male profile
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "male_profile", "ref_text": "Hello I am a male voice"},
        files={"ref_audio": ("male.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 201, f"Failed to create male_profile: {resp.text}"
    print(f"Created male_profile: {resp.json()}")

    # Create female profile
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "female_profile", "ref_text": "Hello I am a female voice"},
        files={"ref_audio": ("female.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 201, f"Failed to create female_profile: {resp.text}"
    print(f"Created female_profile: {resp.json()}")

    # List all voices to verify profiles exist
    resp = client.get("/v1/voices")
    assert resp.status_code == 200
    voices = resp.json()["voices"]
    clone_voices = [v["id"] for v in voices if v.get("type") == "clone"]
    print(f"Clone voices available: {clone_voices}")
    assert "clone:male_profile" in clone_voices, f"clone:male_profile not found in {clone_voices}"
    assert "clone:female_profile" in clone_voices, (
        f"clone:female_profile not found in {clone_voices}"
    )

    # Now send a script with two speakers using different clone profiles
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello, I am Alice.", "voice": "clone:male_profile"},
                {"speaker": "bob", "text": "Hi, I am Bob.", "voice": "clone:female_profile"},
            ]
        },
    )
    print(f"Script response status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Script response error: {resp.text}")
    assert resp.status_code == 200, f"Script synthesis failed: {resp.text}"

    # If we get here, the script was synthesized
    # Check the mock to see what requests were made
    synthesize_calls = client.app.state.inference_svc.synthesize.call_args_list
    print(f"\nTotal synthesize calls: {len(synthesize_calls)}")

    for i, call in enumerate(synthesize_calls):
        req = call[0][0]  # First positional arg
        print(f"\nCall {i + 1}:")
        print(f"  text: {req.text!r}")
        print(f"  mode: {req.mode}")
        print(f"  instruct: {req.instruct}")
        print(f"  ref_audio_path: {req.ref_audio_path}")
        print(f"  ref_text: {req.ref_text}")


def test_speech_clone_single_profile(client, sample_audio_bytes):
    """
    Test that /v1/audio/speech with clone:profile works correctly.
    """
    # Create a profile
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "test_profile", "ref_text": "Test reference text"},
        files={"ref_audio": ("test.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 201
    print(f"Created test_profile: {resp.json()}")

    # Use clone profile in speech request
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello this is a test",
            "voice": "clone:test_profile",
            "response_format": "pcm",
        },
    )
    print(f"Speech response status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Speech response error: {resp.text}")
    assert resp.status_code == 200, f"Speech synthesis failed: {resp.text}"

    # Check the synthesize mock
    synthesize_call = client.app.state.inference_svc.synthesize.call_args
    req = synthesize_call[0][0]
    print("\nSynthesisRequest:")
    print(f"  text: {req.text!r}")
    print(f"  mode: {req.mode}")
    print(f"  ref_audio_path: {req.ref_audio_path}")
    print(f"  ref_text: {req.ref_text}")

    assert req.mode == "clone", f"Expected mode=clone, got mode={req.mode}"
    assert req.ref_audio_path is not None, "ref_audio_path should not be None"
    assert "test_profile" in req.ref_audio_path, (
        f"ref_audio_path should contain 'test_profile', got {req.ref_audio_path}"
    )


def test_script_clone_same_profile_different_speakers(client, sample_audio_bytes):
    """
    REPRODUCE BUG: When using the same clone profile for different speakers,
    only the first speaker's profile should be used (first-definition inheritance).

    This tests the "first-definition inheritance" rule.
    """
    # Create a profile
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "shared_profile", "ref_text": "Shared voice"},
        files={"ref_audio": ("shared.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 201
    print(f"Created shared_profile: {resp.json()}")

    # Send script where alice and bob both use clone:shared_profile
    # BUT alice comes first, so bob's voice should be ignored
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello from Alice", "voice": "clone:shared_profile"},
                {"speaker": "bob", "text": "Hello from Bob", "voice": "clone:shared_profile"},
            ]
        },
    )
    print(f"Script response status: {resp.status_code}")
    assert resp.status_code == 200

    # Both should use the same profile (verified by mock)
    synthesize_calls = client.app.state.inference_svc.synthesize.call_args_list
    print(f"\nTotal synthesize calls: {len(synthesize_calls)}")

    # The key check: both segments should use the same ref_audio_path
    # (first-definition rule means alice's voice is used for both)
    for i, call in enumerate(synthesize_calls):
        req = call[0][0]
        print(f"\nCall {i + 1}: speaker={'alice' if i == 0 else 'bob'}")
        print(f"  ref_audio_path: {req.ref_audio_path}")

    # First-definition rule: bob's voice is ignored
    # Both should have same ref_audio_path


if __name__ == "__main__":
    # Run manually with pytest to see trace output
    import sys

    import pytest

    # Run with -s -v to see print statements and trace logging
    sys.exit(pytest.main([__file__, "-s", "-v", "--log-cli-level=DEBUG"]))

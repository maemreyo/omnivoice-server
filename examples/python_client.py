"""
Python client examples for omnivoice-server.

Demonstrates:
- Basic synthesis
- Voice design
- Voice cloning with profiles
- Streaming audio
"""
import asyncio
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8880"
API_KEY = ""  # Set if server requires auth


def get_headers():
    """Return headers with optional auth."""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


# ── Example 1: Basic synthesis (default design prompt) ──────────────────────


def basic_synthesis():
    """Generate speech with the server's default design prompt."""
    response = httpx.post(
        f"{BASE_URL}/v1/audio/speech",
        headers=get_headers(),
        json={
            "model": "omnivoice",
            "input": "Hello, this is a test of the OmniVoice text-to-speech system.",
            "response_format": "wav",
        },
        timeout=30.0,
    )
    response.raise_for_status()

    output_path = Path("output_basic.wav")
    output_path.write_bytes(response.content)
    print(f"✓ Basic synthesis saved to {output_path}")
    print(f"  Duration: {response.headers.get('X-Audio-Duration-S')}s")
    print(f"  Latency: {response.headers.get('X-Synthesis-Latency-S')}s")


# ── Example 2: Voice design override ─────────────────────────────────────────


def voice_design():
    """Generate speech with designed voice attributes."""
    response = httpx.post(
        f"{BASE_URL}/v1/audio/speech",
        headers=get_headers(),
        json={
            "model": "omnivoice",
            "input": "This voice has been designed with specific attributes.",
            "instructions": "female,british accent,young adult",
            "response_format": "wav",
        },
        timeout=30.0,
    )
    response.raise_for_status()

    output_path = Path("output_design.wav")
    output_path.write_bytes(response.content)
    print(f"✓ Voice design saved to {output_path}")


# ── Example 3: Voice cloning with profile ────────────────────────────────────


def voice_cloning_with_profile():
    """Create a reusable profile for management and inspection."""
    # Step 1: Create a profile (upload reference audio)
    ref_audio_path = Path("reference_audio.wav")
    if not ref_audio_path.exists():
        print(f"⚠ Reference audio not found: {ref_audio_path}")
        print("  Create a profile first using the profile management example.")
        return

    # Create profile
    with open(ref_audio_path, "rb") as f:
        response = httpx.post(
            f"{BASE_URL}/v1/voices/profiles",
            headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
            data={
                "profile_id": "my_voice",
                "ref_text": "This is the reference text spoken in the audio.",
                "overwrite": "true",
            },
            files={"ref_audio": ("reference.wav", f, "audio/wav")},
            timeout=30.0,
        )

    if response.status_code == 201:
        print("✓ Profile created successfully")
    elif response.status_code == 409:
        print("✓ Profile already exists")
    else:
        response.raise_for_status()

    print("✓ Profile is available via /v1/voices and /v1/voices/profiles/{id}")
    print("  /v1/audio/speech ignores `voice`; use /v1/audio/speech/clone to clone audio.")


# ── Example 4: One-shot voice cloning ────────────────────────────────────────


def one_shot_cloning():
    """Clone a voice without saving a profile."""
    ref_audio_path = Path("reference_audio.wav")
    if not ref_audio_path.exists():
        print(f"⚠ Reference audio not found: {ref_audio_path}")
        return

    with open(ref_audio_path, "rb") as f:
        response = httpx.post(
            f"{BASE_URL}/v1/audio/speech/clone",
            headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
            data={
                "text": "This is one-shot voice cloning without saving a profile.",
                "ref_text": "This is the reference text.",
                "speed": "1.0",
            },
            files={"ref_audio": ("reference.wav", f, "audio/wav")},
            timeout=30.0,
        )
    response.raise_for_status()

    output_path = Path("output_oneshot.wav")
    output_path.write_bytes(response.content)
    print(f"✓ One-shot cloning saved to {output_path}")


# ── Example 5: Streaming audio ───────────────────────────────────────────────


async def streaming_synthesis():
    """Stream audio chunks in real-time."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/v1/audio/speech",
            headers=get_headers(),
            json={
                "model": "omnivoice",
                "input": "This is a longer text that will be streamed in chunks. "
                         "Each sentence is synthesized and sent as soon as it's ready. "
                         "This enables lower latency for long-form content.",
                "stream": True,
            },
        ) as response:
            response.raise_for_status()

            sample_rate = response.headers.get("X-Audio-Sample-Rate", "24000")
            print(f"✓ Streaming started (sample_rate={sample_rate}Hz)")

            output_path = Path("output_stream.pcm")
            with open(output_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    print(f"  Received {len(chunk)} bytes")

            print(f"✓ Stream saved to {output_path}")
            print(
                f"  Convert to WAV: ffmpeg -f s16le -ar {sample_rate} "
                f"-ac 1 -i {output_path} output_stream.wav"
            )


# ── Example 6: List available voices ─────────────────────────────────────────


def list_voices():
    """List all available voices and profiles."""
    response = httpx.get(
        f"{BASE_URL}/v1/voices",
        headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
        timeout=10.0,
    )
    response.raise_for_status()

    data = response.json()
    print(f"✓ Available voices ({data['total']} total):")
    for voice in data["voices"]:
        print(f"  - {voice['id']}: {voice.get('description', voice.get('type'))}")


# ── Example 7: Profile management ────────────────────────────────────────────


def manage_profiles():
    """Demonstrate profile CRUD operations."""
    # List profiles
    response = httpx.get(
        f"{BASE_URL}/v1/voices",
        headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
        timeout=10.0,
    )
    response.raise_for_status()
    profiles = [v for v in response.json()["voices"] if v["type"] == "clone"]
    print(f"✓ Found {len(profiles)} profiles")

    # Get specific profile
    if profiles:
        profile_id = profiles[0]["profile_id"]
        response = httpx.get(
            f"{BASE_URL}/v1/voices/profiles/{profile_id}",
            headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
            timeout=10.0,
        )
        response.raise_for_status()
        print(f"✓ Profile details: {response.json()}")

        # Update profile ref_text
        response = httpx.patch(
            f"{BASE_URL}/v1/voices/profiles/{profile_id}",
            headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
            data={"ref_text": "Updated reference text"},
            timeout=10.0,
        )
        if response.status_code == 200:
            print("✓ Profile updated")

        # Delete profile (commented out for safety)
        # response = httpx.delete(
        #     f"{BASE_URL}/v1/voices/profiles/{profile_id}",
        #     headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
        #     timeout=10.0,
        # )
        # print(f"✓ Profile deleted")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    """Run all examples."""
    print("OmniVoice Server - Python Client Examples\n")

    try:
        print("1. Basic synthesis")
        basic_synthesis()
        print()

        print("2. Voice design")
        voice_design()
        print()

        print("3. List voices")
        list_voices()
        print()

        print("4. Profile management")
        manage_profiles()
        print()

        # Uncomment to test cloning (requires reference_audio.wav)
        # print("5. Voice cloning with profile")
        # voice_cloning_with_profile()
        # print()

        # print("6. One-shot cloning")
        # one_shot_cloning()
        # print()

        print("7. Streaming synthesis")
        asyncio.run(streaming_synthesis())
        print()

        print("✓ All examples completed successfully!")

    except httpx.HTTPStatusError as e:
        print(f"✗ HTTP error: {e.response.status_code}")
        print(f"  {e.response.text}")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()

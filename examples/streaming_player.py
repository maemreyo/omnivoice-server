"""
Real-time streaming audio player for omnivoice-server.

Plays PCM audio stream from the server in real-time using pyaudio.

Requirements:
    pip install httpx pyaudio

Usage:
    python streaming_player.py "Your text to synthesize"
"""
import sys

import httpx
import pyaudio

BASE_URL = "http://127.0.0.1:8880"
API_KEY = ""  # Set if server requires auth

# Audio format constants (must match server output)
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
CHUNK_SIZE = 4096


def stream_and_play(
    text: str,
    instructions: str | None = None,
    speed: float = 1.0,
    api_key: str | None = None,
):
    """Stream audio from server and play in real-time."""

    # Initialize PyAudio
    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        output=True,
        frames_per_buffer=CHUNK_SIZE,
    )

    print(f"Streaming: {text[:50]}...")
    print(f"Instructions: {instructions or '[default design prompt]'}, Speed: {speed}x")
    print("Playing audio...")

    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        with httpx.stream(
            "POST",
            f"{BASE_URL}/v1/audio/speech",
            headers=headers,
            json={
                "model": "omnivoice",
                "input": text,
                "instructions": instructions,
                "speed": speed,
                "stream": True,
            },
            timeout=60.0,
        ) as response:
            response.raise_for_status()

            # Verify audio format from headers
            sample_rate = int(response.headers.get("X-Audio-Sample-Rate", SAMPLE_RATE))
            if sample_rate != SAMPLE_RATE:
                print(f"Warning: Server sample rate {sample_rate}Hz != expected {SAMPLE_RATE}Hz")

            # Stream and play chunks
            bytes_received = 0
            for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                stream.write(chunk)
                bytes_received += len(chunk)

            duration_s = bytes_received / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
            print("\n✓ Playback complete")
            print(f"  Received: {bytes_received:,} bytes")
            print(f"  Duration: {duration_s:.2f}s")

    except httpx.HTTPStatusError as e:
        print(f"\n✗ HTTP error: {e.response.status_code}")
        print(f"  {e.response.text}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python streaming_player.py <text> [instructions] [speed]")
        print()
        print("Examples:")
        print('  python streaming_player.py "Hello world"')
        print('  python streaming_player.py "Hello world" "female,british accent"')
        print('  python streaming_player.py "Hello world" "male,deep voice" 1.2')
        sys.exit(1)

    text = sys.argv[1]
    instructions = sys.argv[2] if len(sys.argv) > 2 else None
    speed = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    stream_and_play(text, instructions, speed, API_KEY)


if __name__ == "__main__":
    main()

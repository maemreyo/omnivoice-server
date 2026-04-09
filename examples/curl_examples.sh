#!/bin/bash
#
# cURL examples for omnivoice-server API
#
# Usage: ./curl_examples.sh
#

set -e

BASE_URL="http://127.0.0.1:8880"
API_KEY=""  # Set if server requires auth

# Helper function for auth header
auth_header() {
    if [ -n "$API_KEY" ]; then
        echo "-H \"Authorization: Bearer $API_KEY\""
    fi
}

echo "=== OmniVoice Server cURL Examples ==="
echo

# ── Example 1: Basic synthesis (default design prompt) ──────────────────────

echo "1. Basic synthesis (default design prompt)"
curl -X POST "$BASE_URL/v1/audio/speech" \
  $(auth_header) \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Hello, this is a test of the OmniVoice text-to-speech system.",
    "response_format": "wav"
  }' \
  --output output_basic.wav \
  --silent --show-error --write-out "\n✓ Saved to output_basic.wav (HTTP %{http_code})\n"

echo

# ── Example 2: Voice design ──────────────────────────────────────────────────

echo "2. Voice design with attributes"
curl -X POST "$BASE_URL/v1/audio/speech" \
  $(auth_header) \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "This voice has been designed with specific attributes.",
    "instructions": "female,british accent,young adult",
    "response_format": "wav"
  }' \
  --output output_design.wav \
  --silent --show-error --write-out "\n✓ Saved to output_design.wav (HTTP %{http_code})\n"

echo

# ── Example 3: Streaming synthesis ───────────────────────────────────────────

echo "3. Streaming synthesis (PCM output)"
curl -X POST "$BASE_URL/v1/audio/speech" \
  $(auth_header) \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "This is a longer text that will be streamed in chunks. Each sentence is synthesized and sent as soon as it is ready.",
    "stream": true
  }' \
  --output output_stream.pcm \
  --silent --show-error --write-out "\n✓ Saved to output_stream.pcm (HTTP %{http_code})\n"

echo "  Convert to WAV: ffmpeg -f s16le -ar 24000 -ac 1 -i output_stream.pcm output_stream.wav"
echo

# ── Example 4: List voices ───────────────────────────────────────────────────

echo "4. List available voices"
curl -X GET "$BASE_URL/v1/voices" \
  $(auth_header) \
  --silent --show-error | jq '.'

echo

# ── Example 5: Create voice profile ──────────────────────────────────────────

echo "5. Create voice cloning profile"
echo "  (Requires reference_audio.wav file)"

if [ -f "reference_audio.wav" ]; then
    curl -X POST "$BASE_URL/v1/voices/profiles" \
      $(auth_header) \
      -F "profile_id=my_voice" \
      -F "ref_audio=@reference_audio.wav" \
      -F "ref_text=This is the reference text spoken in the audio." \
      -F "overwrite=true" \
      --silent --show-error | jq '.'
    echo
else
    echo "  ⚠ reference_audio.wav not found, skipping"
    echo
fi

# ── Example 6: Stored profile note ───────────────────────────────────────────

echo "6. Stored profiles are listed via /v1/voices, but /v1/audio/speech ignores voice"
echo "  Use /v1/audio/speech/clone for actual voice cloning synthesis"

echo

# ── Example 7: One-shot voice cloning ────────────────────────────────────────

echo "7. One-shot voice cloning (no profile)"
echo "  (Requires reference_audio.wav file)"

if [ -f "reference_audio.wav" ]; then
    curl -X POST "$BASE_URL/v1/audio/speech/clone" \
      $(auth_header) \
      -F "text=This is one-shot voice cloning without saving a profile." \
      -F "ref_audio=@reference_audio.wav" \
      -F "ref_text=This is the reference text." \
      -F "speed=1.0" \
      --output output_oneshot.wav \
      --silent --show-error --write-out "\n✓ Saved to output_oneshot.wav (HTTP %{http_code})\n"
    echo
else
    echo "  ⚠ reference_audio.wav not found, skipping"
    echo
fi

# ── Example 8: Get profile details ───────────────────────────────────────────

echo "8. Get profile details"
curl -X GET "$BASE_URL/v1/voices/profiles/my_voice" \
  $(auth_header) \
  --silent --show-error | jq '.' \
  || echo "  ⚠ Profile 'my_voice' not found"

echo

# ── Example 9: Update profile ────────────────────────────────────────────────

echo "9. Update profile ref_text"
curl -X PATCH "$BASE_URL/v1/voices/profiles/my_voice" \
  $(auth_header) \
  -F "ref_text=Updated reference text for the voice profile." \
  --silent --show-error | jq '.' \
  || echo "  ⚠ Profile 'my_voice' not found"

echo

# ── Example 10: Delete profile ───────────────────────────────────────────────

echo "10. Delete profile (commented out for safety)"
echo "  # curl -X DELETE \"$BASE_URL/v1/voices/profiles/my_voice\" $(auth_header)"
echo

# ── Example 11: List models ──────────────────────────────────────────────────

echo "11. List available models"
curl -X GET "$BASE_URL/v1/models" \
  $(auth_header) \
  --silent --show-error | jq '.'

echo

# ── Example 12: Health check ─────────────────────────────────────────────────

echo "12. Health check"
curl -X GET "$BASE_URL/health" \
  --silent --show-error | jq '.'

echo

echo "✓ All examples completed!"

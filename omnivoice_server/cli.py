"""CLI entrypoint for omnivoice-server."""

from __future__ import annotations

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="omnivoice-server",
        description="OpenAI-compatible HTTP server for OmniVoice TTS",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Server
    parser.add_argument("--host", default=None, help="Bind host (env: OMNIVOICE_HOST)")
    parser.add_argument("--port", type=int, default=None, help="Port (env: OMNIVOICE_PORT)")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["debug", "info", "warning", "error"],
        help="Log level (env: OMNIVOICE_LOG_LEVEL)",
    )

    # Model
    parser.add_argument(
        "--model",
        default=None,
        dest="model_id",
        help="HuggingFace model ID or local path (env: OMNIVOICE_MODEL_ID)",
    )
    parser.add_argument(
        "--device",
        default=None,
        choices=["auto", "cuda", "mps", "cpu"],
        help="Inference device (env: OMNIVOICE_DEVICE)",
    )
    parser.add_argument(
        "--num-step",
        type=int,
        default=None,
        dest="num_step",
        help="Diffusion steps, 1-64 (env: OMNIVOICE_NUM_STEP)",
    )
    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=None,
        dest="guidance_scale",
        help="CFG scale, 0-10 (env: OMNIVOICE_GUIDANCE_SCALE)",
    )
    parser.add_argument(
        "--denoise",
        action="store_true",
        default=None,
        dest="denoise",
        help="Enable denoising (env: OMNIVOICE_DENOISE)",
    )
    parser.add_argument(
        "--no-denoise",
        action="store_false",
        dest="denoise",
        help="Disable denoising",
    )
    parser.add_argument(
        "--t-shift",
        type=float,
        default=None,
        dest="t_shift",
        help="Noise schedule shift, 0-2 (env: OMNIVOICE_T_SHIFT)",
    )
    parser.add_argument(
        "--position-temperature",
        type=float,
        default=None,
        dest="position_temperature",
        help="Voice diversity temperature, 0-10 (env: OMNIVOICE_POSITION_TEMPERATURE)",
    )
    parser.add_argument(
        "--class-temperature",
        type=float,
        default=None,
        dest="class_temperature",
        help="Token sampling temperature, 0-2 (env: OMNIVOICE_CLASS_TEMPERATURE)",
    )

    # Inference
    parser.add_argument(
        "--stream",
        action="store_true",
        default=None,
        dest="stream",
        help="Force-enable streaming for all requests (env: OMNIVOICE_STREAM)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_false",
        dest="stream",
        help="Disable forced streaming",
    )
    parser.add_argument(
        "--stream-overlap",
        action="store_true",
        default=None,
        dest="stream_overlap",
        help="Enable overlapped sentence streaming (env: OMNIVOICE_STREAM_OVERLAP)",
    )
    parser.add_argument(
        "--no-stream-overlap",
        action="store_false",
        dest="stream_overlap",
        help="Disable overlapped sentence streaming",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        dest="max_concurrent",
        help="Max simultaneous inferences (env: OMNIVOICE_MAX_CONCURRENT)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        dest="request_timeout_s",
        help="Request timeout in seconds (env: OMNIVOICE_REQUEST_TIMEOUT_S)",
    )
    parser.add_argument(
        "--cleanup-interval",
        type=int,
        default=None,
        dest="cleanup_interval",
        help=(
            "Run memory cleanup every N syntheses. 0 disables it "
            "(env: OMNIVOICE_CLEANUP_INTERVAL)"
        ),
    )
    parser.add_argument(
        "--cuda-alloc-conf",
        default=None,
        dest="cuda_alloc_conf",
        help=(
            "Set PYTORCH_CUDA_ALLOC_CONF before CUDA init. "
            "Use 'off' to disable the server override "
            "(env: OMNIVOICE_CUDA_ALLOC_CONF)"
        ),
    )
    parser.add_argument(
        "--offload-voice-encoder",
        action="store_true",
        default=None,
        dest="offload_voice_encoder",
        help="Keep voice-reference encoder modules off GPU between preparations",
    )
    parser.add_argument(
        "--no-offload-voice-encoder",
        action="store_false",
        dest="offload_voice_encoder",
        help="Keep voice-reference encoder modules resident",
    )
    parser.add_argument(
        "--skip-voice-encoder",
        action="store_true",
        default=None,
        dest="skip_voice_encoder",
        help="Request skip_encoder=True from compatible OmniVoice builds",
    )
    parser.add_argument(
        "--no-skip-voice-encoder",
        action="store_false",
        dest="skip_voice_encoder",
        help="Use the standard OmniVoice loader",
    )
    parser.add_argument(
        "--low-vram",
        action="store_true",
        default=None,
        dest="low_vram_mode",
        help="Enable opt-in decoder-only tokenizer loading (env: OMNIVOICE_LOW_VRAM_MODE)",
    )
    parser.add_argument(
        "--no-low-vram",
        action="store_false",
        dest="low_vram_mode",
        help="Disable decoder-only tokenizer loading",
    )
    parser.add_argument(
        "--flashinfer",
        action="store_true",
        default=None,
        dest="flashinfer_mode",
        help="Enable optional FlashInfer CUDA acceleration (env: OMNIVOICE_FLASHINFER_MODE)",
    )
    parser.add_argument(
        "--no-flashinfer",
        action="store_false",
        dest="flashinfer_mode",
        help="Disable FlashInfer acceleration",
    )
    parser.add_argument(
        "--flashinfer-cuda-graph",
        action="store_true",
        default=None,
        dest="flashinfer_cuda_graph",
        help="Enable FlashInfer CUDA graphs (env: OMNIVOICE_FLASHINFER_CUDA_GRAPH)",
    )
    parser.add_argument(
        "--flashinfer-cuda-graph-max-shapes",
        type=int,
        default=None,
        dest="flashinfer_cuda_graph_max_shapes",
        help=(
            "Maximum retained FlashInfer CUDA-graph shapes (env: "
            "OMNIVOICE_FLASHINFER_CUDA_GRAPH_MAX_SHAPES)"
        ),
    )
    parser.add_argument(
        "--split-cfg-batch",
        action="store_true",
        default=None,
        dest="split_cfg_batch",
        help="Reduce standard-path peak VRAM by splitting CFG forwards",
    )
    parser.add_argument(
        "--no-split-cfg-batch",
        action="store_false",
        dest="split_cfg_batch",
        help="Keep the standard combined CFG forward",
    )
    parser.add_argument(
        "--tf32",
        action="store_true",
        default=None,
        dest="cuda_tf32",
        help="Enable CUDA TF32 matmul fast paths",
    )
    parser.add_argument(
        "--no-tf32",
        action="store_false",
        dest="cuda_tf32",
        help="Disable CUDA TF32 matmul fast paths",
    )
    parser.add_argument(
        "--transcriber",
        choices=["whisper", "faster-whisper"],
        default=None,
        help="Automatic reference transcription backend",
    )
    parser.add_argument("--asr-model", default=None, dest="asr_model_name")
    parser.add_argument(
        "--asr-device", choices=["auto", "cuda", "cpu"], default=None, dest="asr_device"
    )
    parser.add_argument("--asr-language", default=None, dest="asr_language")
    parser.add_argument("--asr-beam-size", type=int, default=None, dest="asr_beam_size")
    parser.add_argument(
        "--shutdown-timeout",
        type=int,
        default=None,
        dest="shutdown_timeout",
        help="Seconds to wait for in-flight requests on shutdown (env: OMNIVOICE_SHUTDOWN_TIMEOUT)",
    )

    # Storage
    parser.add_argument(
        "--profile-dir",
        default=None,
        dest="profile_dir",
        help="Voice profile directory (env: OMNIVOICE_PROFILE_DIR)",
    )
    parser.add_argument(
        "--allow-private-voice-urls",
        action="store_true",
        default=None,
        dest="allow_private_voice_urls",
        help="Allow voice_url downloads from loopback/private networks",
    )
    parser.add_argument(
        "--no-allow-private-voice-urls",
        action="store_false",
        dest="allow_private_voice_urls",
        help="Require voice_url downloads to resolve only to public addresses",
    )

    # Auth
    parser.add_argument(
        "--api-key",
        default=None,
        dest="api_key",
        help="Bearer token for auth. Empty = no auth (env: OMNIVOICE_API_KEY)",
    )
    parser.add_argument(
        "--cors-origins",
        default=None,
        dest="cors_allow_origins",
        help=("Comma-separated allowed CORS origins (env: OMNIVOICE_CORS_ALLOW_ORIGINS)"),
    )
    parser.add_argument(
        "--cors-allow-credentials",
        action="store_true",
        default=None,
        dest="cors_allow_credentials",
        help="Allow credentialed CORS requests (env: OMNIVOICE_CORS_ALLOW_CREDENTIALS)",
    )
    parser.add_argument(
        "--no-cors-allow-credentials",
        action="store_false",
        dest="cors_allow_credentials",
        help="Disable credentialed CORS requests",
    )

    args = parser.parse_args()

    overrides = {k: v for k, v in vars(args).items() if v is not None}

    from .config import Settings

    cfg = Settings(**overrides)

    import sys

    logging.basicConfig(
        level=cfg.log_level.upper(),
        format="%(asctime)s [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stderr,
    )

    import uvicorn

    from .app import create_app

    app = create_app(cfg)

    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level,
        workers=1,
        loop="asyncio",
        timeout_graceful_shutdown=cfg.shutdown_timeout,
    )


if __name__ == "__main__":
    main()

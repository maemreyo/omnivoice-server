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
    parser.add_argument(
        "--host", default=None, help="Bind host (env: OMNIVOICE_HOST)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Port (env: OMNIVOICE_PORT)"
    )
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

    # Inference
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

    # Storage
    parser.add_argument(
        "--profile-dir",
        default=None,
        dest="profile_dir",
        help="Voice profile directory (env: OMNIVOICE_PROFILE_DIR)",
    )

    # Auth
    parser.add_argument(
        "--api-key",
        default=None,
        dest="api_key",
        help="Bearer token for auth. Empty = no auth (env: OMNIVOICE_API_KEY)",
    )

    args = parser.parse_args()

    # Build override dict
    overrides = {k: v for k, v in vars(args).items() if v is not None}

    from .config import Settings
    cfg = Settings(**overrides)

    # Configure logging
    logging.basicConfig(
        level=cfg.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
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
    )


if __name__ == "__main__":
    main()

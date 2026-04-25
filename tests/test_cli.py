"""Tests for CLI argument parsing."""

from __future__ import annotations


def test_cli_stream_flag_parsed():
    """--stream should set stream=True in overrides passed to Settings."""
    import argparse

    from omnivoice_server.config import Settings

    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", action="store_true", default=None, dest="stream")
    parser.add_argument("--no-stream", action="store_false", dest="stream")
    args = parser.parse_args(["--stream"])
    overrides = {k: v for k, v in vars(args).items() if v is not None}
    assert overrides["stream"] is True
    # Validate Settings accepts the override
    Settings(**overrides)


def test_cli_no_stream_flag_parsed():
    """--no-stream should set stream=False in overrides passed to Settings."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", action="store_true", default=None, dest="stream")
    parser.add_argument("--no-stream", action="store_false", dest="stream")
    args = parser.parse_args(["--no-stream"])
    overrides = {k: v for k, v in vars(args).items() if v is not None}
    assert overrides["stream"] is False


def test_cli_stream_env_var_parsed():
    """OMNIVOICE_STREAM=true should be picked up by Settings."""
    import os

    from omnivoice_server.config import Settings

    env = os.environ.copy()
    env["OMNIVOICE_STREAM"] = "true"
    # Pydantic-settings reads env automatically when instantiated inside that env
    prev = os.environ.get("OMNIVOICE_STREAM")
    os.environ["OMNIVOICE_STREAM"] = "true"
    try:
        cfg = Settings()
        assert cfg.stream is True
    finally:
        if prev is None:
            os.environ.pop("OMNIVOICE_STREAM", None)
        else:
            os.environ["OMNIVOICE_STREAM"] = prev


def test_cli_stream_overlap_flag_parsed():
    import argparse

    from omnivoice_server.config import Settings

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stream-overlap",
        action="store_true",
        default=None,
        dest="stream_overlap",
    )
    parser.add_argument("--no-stream-overlap", action="store_false", dest="stream_overlap")
    args = parser.parse_args(["--stream-overlap"])
    overrides = {k: v for k, v in vars(args).items() if v is not None}
    assert overrides["stream_overlap"] is True
    Settings(**overrides)


def test_cli_no_stream_overlap_flag_parsed():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stream-overlap",
        action="store_true",
        default=None,
        dest="stream_overlap",
    )
    parser.add_argument("--no-stream-overlap", action="store_false", dest="stream_overlap")
    args = parser.parse_args(["--no-stream-overlap"])
    overrides = {k: v for k, v in vars(args).items() if v is not None}
    assert overrides["stream_overlap"] is False


def test_stream_overlap_default_is_false():
    from omnivoice_server.config import Settings

    assert Settings().stream_overlap is False


def test_stream_overlap_env_var_parsed():
    import os

    from omnivoice_server.config import Settings

    prev = os.environ.get("OMNIVOICE_STREAM_OVERLAP")
    os.environ["OMNIVOICE_STREAM_OVERLAP"] = "true"
    try:
        cfg = Settings()
        assert cfg.stream_overlap is True
    finally:
        if prev is None:
            os.environ.pop("OMNIVOICE_STREAM_OVERLAP", None)
        else:
            os.environ["OMNIVOICE_STREAM_OVERLAP"] = prev

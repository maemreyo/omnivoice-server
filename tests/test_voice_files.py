"""
Voice designs stored as .txt files in a directory (issue #38).
"""

from __future__ import annotations

import pytest

from omnivoice_server.services.voice_files import (
    VoiceFileError,
    VoiceFileService,
    parse_voice_file,
)

# ── Parsing ──────────────────────────────────────────────────────────────────


def test_bare_attribute_line_is_the_voice_design():
    voice = parse_voice_file("young adult, canadian accent, female", "canadian")
    assert voice.name == "canadian"
    assert "canadian accent" in voice.instructions
    assert voice.params == {}


def test_settings_are_parsed_and_typed():
    voice = parse_voice_file(
        "female, young adult, high pitch\nseed: 4242\nspeed: 0.95\nnum_step: 16\ndenoise: false",
        "v",
    )
    assert voice.params == {
        "seed": 4242,
        "speed": 0.95,
        "num_step": 16,
        "denoise": False,
    }


def test_equals_separator_is_accepted():
    assert parse_voice_file("female\nseed = 7", "v").params == {"seed": 7}


def test_comments_and_blank_lines_are_ignored():
    voice = parse_voice_file("# my notes\n\nfemale, british accent\n\n# more\nseed: 1", "v")
    assert voice.params == {"seed": 1}
    assert "british accent" in voice.instructions


def test_multiple_attribute_lines_are_joined():
    voice = parse_voice_file("female\nbritish accent\nhigh pitch", "v")
    for attribute in ("female", "british accent", "high pitch"):
        assert attribute in voice.instructions


def test_explicit_instructions_key_wins_over_loose_lines():
    voice = parse_voice_file("instructions: male, british accent", "v")
    assert "male" in voice.instructions


def test_description_is_metadata_not_voice_attributes():
    voice = parse_voice_file("description: For audiobooks\nfemale, british accent", "v")
    assert voice.description == "For audiobooks"
    assert "audiobook" not in voice.instructions.lower()


def test_empty_file_is_rejected():
    with pytest.raises(VoiceFileError, match="no voice attributes"):
        parse_voice_file("# only a comment\n\n", "v")


def test_invalid_attributes_are_rejected():
    with pytest.raises(VoiceFileError):
        parse_voice_file("cheerful, enthusiastic", "v")


def test_unknown_setting_is_rejected_by_name():
    """
    Treating it as voice attributes instead would fail validation with a
    message pointing at the wrong thing.
    """
    with pytest.raises(VoiceFileError, match="unknown setting 'volume'"):
        parse_voice_file("female\nvolume: 11", "v")


def test_non_numeric_value_names_the_offending_line():
    with pytest.raises(VoiceFileError, match="line 2"):
        parse_voice_file("female\nseed: not-a-number", "v")


def test_bad_boolean_is_rejected():
    with pytest.raises(VoiceFileError, match="true/false"):
        parse_voice_file("female\ndenoise: maybe", "v")


# ── Directory service ────────────────────────────────────────────────────────


@pytest.fixture
def voice_dir(tmp_path):
    (tmp_path / "narrator.txt").write_text("male, middle-aged, british accent\nseed: 99")
    (tmp_path / "presenter.txt").write_text("female, young adult, american accent")
    return tmp_path


def test_lists_voices_sorted_by_name(voice_dir):
    svc = VoiceFileService(voice_dir)
    assert [v.name for v in svc.list_voices()] == ["narrator", "presenter"]


def test_lookup_by_name(voice_dir):
    voice = VoiceFileService(voice_dir).get("narrator")
    assert voice is not None
    assert voice.params == {"seed": 99}


def test_lookup_is_case_insensitive(voice_dir):
    assert VoiceFileService(voice_dir).get("NARRATOR") is not None


def test_missing_voice_returns_none(voice_dir):
    assert VoiceFileService(voice_dir).get("nobody") is None


def test_missing_directory_is_not_an_error(tmp_path):
    svc = VoiceFileService(tmp_path / "does-not-exist")
    assert svc.list_voices() == []
    assert svc.get("anything") is None


def test_unparseable_file_is_skipped_not_fatal(voice_dir):
    (voice_dir / "broken.txt").write_text("cheerful and excited")
    names = [v.name for v in VoiceFileService(voice_dir).list_voices()]
    assert names == ["narrator", "presenter"]


def test_unsafe_filename_is_skipped(voice_dir):
    (voice_dir / "not a valid name!.txt").write_text("female, british accent")
    names = [v.name for v in VoiceFileService(voice_dir).list_voices()]
    assert names == ["narrator", "presenter"]


def test_non_txt_files_are_ignored(voice_dir):
    (voice_dir / "readme.md").write_text("female, british accent")
    assert len(VoiceFileService(voice_dir).list_voices()) == 2


def test_edited_file_is_re_read_without_restart(voice_dir):
    svc = VoiceFileService(voice_dir)
    assert svc.get("narrator").params == {"seed": 99}

    target = voice_dir / "narrator.txt"
    target.write_text("male, middle-aged, british accent\nseed: 1234")
    # Cache is keyed on mtime and size; force a distinct mtime.
    import os

    stat = target.stat()
    os.utime(target, (stat.st_atime, stat.st_mtime + 10))

    assert svc.get("narrator").params == {"seed": 1234}


def test_new_file_is_picked_up_without_restart(voice_dir):
    svc = VoiceFileService(voice_dir)
    assert svc.get("late-arrival") is None
    (voice_dir / "late-arrival.txt").write_text("female, british accent")
    assert svc.get("late-arrival") is not None

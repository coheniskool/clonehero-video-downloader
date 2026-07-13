"""sanitize_chorus_field(): reject unsafe values before they reach song.ini.

Chorus-sourced fields are spliced into song.ini via regex substitution, not
parsed by configparser -- an unsanitized value with a stray [, ], ;, #, or
embedded newline could corrupt the file or desync a later key. Reject
rather than partially clean, so a bad value never silently becomes a
different bad value.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_chorus_sanitize_test', MODULE_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


def test_accepts_a_clean_value():
	assert module.sanitize_chorus_field("Post-Grunge") == "Post-Grunge"


def test_strips_surrounding_whitespace():
	assert module.sanitize_chorus_field("  Post-Grunge  ") == "Post-Grunge"


def test_rejects_none():
	assert module.sanitize_chorus_field(None) is None


def test_rejects_non_string():
	assert module.sanitize_chorus_field(12345) is None


def test_rejects_empty_string():
	assert module.sanitize_chorus_field("") is None
	assert module.sanitize_chorus_field("   ") is None


def test_rejects_embedded_open_bracket():
	assert module.sanitize_chorus_field("Rock [Remastered]") is None


def test_rejects_embedded_close_bracket():
	assert module.sanitize_chorus_field("Rock Remastered]") is None


def test_rejects_embedded_semicolon():
	assert module.sanitize_chorus_field("Rock; drop_table") is None


def test_rejects_embedded_hash():
	assert module.sanitize_chorus_field("Rock #1 hit") is None


def test_rejects_embedded_newline():
	assert module.sanitize_chorus_field("Rock\nvideo_start_time = 99999") is None


def test_rejects_embedded_carriage_return():
	assert module.sanitize_chorus_field("Rock\rSomething") is None


def test_rejects_invalid_utf8_surrogate():
	assert module.sanitize_chorus_field("Rock\ud800Genre") is None


def test_truncates_oversized_values():
	huge = "A" * 500
	result = module.sanitize_chorus_field(huge)
	assert result is not None
	assert len(result) == 200

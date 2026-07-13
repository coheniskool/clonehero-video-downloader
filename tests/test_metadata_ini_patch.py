"""Byte-preserving, atomic patch_song_ini_keys() -- the multi-key generalization
of patch_song_ini() (which only ever touches video_start_time).

Reuses the same discipline: every other line preserved byte-for-byte
(including CRLF vs LF), missing keys inserted under [Song], never a
partially-written file.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_metadata_patch_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


def test_fills_multiple_missing_keys_under_song_section(tmp_path):
	ini = tmp_path / "song.ini"
	ini.write_text("[Song]\nname = Kryptonite\nartist = 3 Doors Down\n", encoding="utf-8", newline="")

	CH.patch_song_ini_keys(str(tmp_path), {"year": "1999", "genre": "Post-Grunge"})

	content = ini.read_text(encoding="utf-8")
	assert "year = 1999" in content
	assert "genre = Post-Grunge" in content
	assert "name = Kryptonite" in content
	assert "artist = 3 Doors Down" in content


def test_updates_an_existing_key_in_place_case_insensitive(tmp_path):
	ini = tmp_path / "song.ini"
	ini.write_text("[Song]\nName = Kryptonite\nYear = \n", encoding="utf-8", newline="")

	CH.patch_song_ini_keys(str(tmp_path), {"year": "1999"})

	lines = ini.read_text(encoding="utf-8").splitlines()
	assert lines[0] == "[Song]"
	assert lines[1] == "Name = Kryptonite"
	assert lines[2] == "year = 1999"


def test_preserves_crlf_line_endings(tmp_path):
	ini = tmp_path / "song.ini"
	ini.write_bytes(b"[Song]\r\nname = Kryptonite\r\n")

	CH.patch_song_ini_keys(str(tmp_path), {"genre": "Post-Grunge"})

	raw = ini.read_bytes()
	assert b"\r\n" in raw
	assert b"\n\n" not in raw.replace(b"\r\n", b"")


def test_preserves_lf_line_endings(tmp_path):
	ini = tmp_path / "song.ini"
	ini.write_bytes(b"[Song]\nname = Kryptonite\n")

	CH.patch_song_ini_keys(str(tmp_path), {"genre": "Post-Grunge"})

	raw = ini.read_bytes()
	assert b"\r\n" not in raw


def test_does_not_touch_unrelated_keys_or_comments(tmp_path):
	ini = tmp_path / "song.ini"
	original = "[Song]\nname = Kryptonite\nartist = 3 Doors Down\nvideo_start_time = 816\n"
	ini.write_text(original, encoding="utf-8", newline="")

	CH.patch_song_ini_keys(str(tmp_path), {"year": "1999"})

	content = ini.read_text(encoding="utf-8")
	assert "video_start_time = 816" in content
	assert "artist = 3 Doors Down" in content


def test_empty_updates_dict_touches_nothing(tmp_path):
	ini = tmp_path / "song.ini"
	original = "[Song]\nname = Kryptonite\n"
	ini.write_text(original, encoding="utf-8", newline="")

	CH.patch_song_ini_keys(str(tmp_path), {})

	assert ini.read_text(encoding="utf-8") == original


def test_returns_none_when_no_ini_file(tmp_path):
	result = CH.patch_song_ini_keys(str(tmp_path), {"year": "1999"})

	assert result is None


def test_write_failure_leaves_original_untouched(tmp_path, monkeypatch):
	ini = tmp_path / "song.ini"
	original = "[Song]\nname = Kryptonite\n"
	ini.write_text(original, encoding="utf-8", newline="")

	def _boom(*args, **kwargs):
		raise OSError("disk full")

	monkeypatch.setattr(CH.os, "replace", _boom)

	try:
		CH.patch_song_ini_keys(str(tmp_path), {"year": "1999"})
		assert False, "expected an OSError"
	except OSError:
		pass

	assert ini.read_text(encoding="utf-8") == original

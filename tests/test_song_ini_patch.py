"""Byte-preserving, atomic patch_song_ini().

Supersedes update_ini_with_offset(), which had two real bugs: it interchanged
video_start_time with the chart-internal offset/song_offset/video_offset keys
(clobbering whichever it found first), and it wasn't atomic. patch_song_ini()
must touch video_start_time only, preserve every other line byte-for-byte
(including CRLF vs LF), and never leave a partially-written file behind.
"""

import importlib.util
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_patch_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


REAL_SHAPED_INI = (
	"[song]\n"
	"name = Kryptonite\n"
	"artist = 3 Doors Down\n"
	"album = The Better Life\n"
	"video = \n"
	"video_start_time = 0\n"
	"preview_start_time = -1\n"
	"song_length = 240389\n"
	"delay = 0\n"
	"modchart = 0\n"
)


def test_updates_existing_video_start_time_preserving_other_lines(tmp_path):
	ini = tmp_path / "song.ini"
	ini.write_text(REAL_SHAPED_INI, encoding="utf-8", newline="")

	result = CH.patch_song_ini(str(tmp_path), 1234)

	assert result == ini
	new_content = ini.read_text(encoding="utf-8")
	new_lines = new_content.splitlines()
	old_lines = REAL_SHAPED_INI.splitlines()
	for old_line, new_line in zip(old_lines, new_lines):
		if old_line.startswith("video_start_time"):
			assert new_line == "video_start_time = 1234"
		else:
			assert new_line == old_line
	assert len(new_lines) == len(old_lines)


def test_case_insensitive_key_match(tmp_path):
	ini = tmp_path / "song.ini"
	ini.write_text("[Song]\nName = Test\nVideo_Start_Time = 0\n", encoding="utf-8", newline="")

	CH.patch_song_ini(str(tmp_path), 500)

	content = ini.read_text(encoding="utf-8")
	assert "Name = Test" in content
	assert "500" in content
	# only one video_start_time-ish line should remain, and its value is 500
	lines = [l for l in content.splitlines() if "video_start_time" in l.lower()]
	assert len(lines) == 1
	assert lines[0].strip().endswith("500")


def test_inserts_missing_key_under_song_section(tmp_path):
	ini = tmp_path / "song.ini"
	original = "[Song]\nname = Test Song\nartist = Test Artist\n"
	ini.write_text(original, encoding="utf-8", newline="")

	CH.patch_song_ini(str(tmp_path), 777)

	content = ini.read_text(encoding="utf-8")
	lines = content.splitlines()
	assert lines[0] == "[Song]"
	assert "video_start_time = 777" in lines
	assert "name = Test Song" in lines
	assert "artist = Test Artist" in lines


def test_preserves_crlf_line_endings(tmp_path):
	ini = tmp_path / "song.ini"
	original = "[Song]\r\nname = Test\r\nvideo_start_time = 0\r\n"
	ini.write_text(original, encoding="utf-8", newline="")

	CH.patch_song_ini(str(tmp_path), 42)

	raw = ini.read_bytes()
	assert b"\r\n" in raw
	assert b"\n\r" not in raw  # sanity: not double-converted
	# every line ending in the output should be CRLF, none bare LF
	text = raw.decode("utf-8")
	assert "\r\n" in text
	for line in text.split("\r\n")[:-1]:
		assert "\n" not in line


def test_preserves_lf_line_endings(tmp_path):
	ini = tmp_path / "song.ini"
	original = "[Song]\nname = Test\nvideo_start_time = 0\n"
	ini.write_text(original, encoding="utf-8", newline="")

	CH.patch_song_ini(str(tmp_path), 42)

	raw = ini.read_bytes()
	assert b"\r\n" not in raw


def test_does_not_touch_chart_offset_key_appearing_before_video_start_time(tmp_path):
	ini = tmp_path / "song.ini"
	# a chart with a stray "offset" key (chart-internal timing, unrelated to video)
	# appearing before video_start_time -- must never be touched
	original = "[Song]\nname = Test\noffset = 5\nvideo_start_time = 0\n"
	ini.write_text(original, encoding="utf-8", newline="")

	CH.patch_song_ini(str(tmp_path), 999)

	content = ini.read_text(encoding="utf-8")
	assert "offset = 5" in content
	assert "video_start_time = 999" in content


def test_write_failure_leaves_original_untouched(tmp_path, monkeypatch):
	ini = tmp_path / "song.ini"
	ini.write_text(REAL_SHAPED_INI, encoding="utf-8", newline="")

	def boom(*args, **kwargs):
		raise OSError("simulated failure")

	monkeypatch.setattr(os, "replace", boom)

	with pytest.raises(OSError):
		CH.patch_song_ini(str(tmp_path), 1234)

	assert ini.read_text(encoding="utf-8") == REAL_SHAPED_INI


def test_returns_none_when_no_ini_file(tmp_path):
	result = CH.patch_song_ini(str(tmp_path), 1234)

	assert result is None
	assert list(tmp_path.iterdir()) == []

"""ID-suffix detection for song.ini/notes.chart/notes.mid.

Some song folders ship with numeric-ID-suffixed chart filenames instead of the
literal names Clone Hero requires (song_2400.ini, notes_454.chart, notes_232.mid)
-- confirmed against the real library during 2026-07-12 triage. This module's
job at this stage is detection only: classify a folder's naming state without
verifying content or renaming anything (that's Tasks 2/3/3b/3c/4).
"""

import clonehero_video_offset as module


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


def test_ok_when_song_ini_and_notes_chart_are_literal(tmp_path):
	_touch(tmp_path / "song.ini")
	_touch(tmp_path / "notes.chart")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "ok"


def test_ok_when_song_ini_and_notes_mid_are_literal(tmp_path):
	_touch(tmp_path / "song.ini")
	_touch(tmp_path / "notes.mid")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "ok"


def test_id_suffixed_when_ini_has_numeric_suffix(tmp_path):
	_touch(tmp_path / "song_2400.ini")
	_touch(tmp_path / "notes.mid")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "id_suffixed"
	assert "song_2400.ini" in result["detail"]


def test_id_suffixed_when_notes_chart_has_numeric_suffix(tmp_path):
	_touch(tmp_path / "song.ini")
	_touch(tmp_path / "notes_454.chart")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "id_suffixed"
	assert "notes_454.chart" in result["detail"]


def test_id_suffixed_when_notes_mid_has_numeric_suffix(tmp_path):
	_touch(tmp_path / "song.ini")
	_touch(tmp_path / "notes_232.mid")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "id_suffixed"
	assert "notes_232.mid" in result["detail"]


def test_id_suffixed_when_both_ini_and_chart_have_numeric_suffix(tmp_path):
	# the real Mr. Roboto/You Only Live Once shape: every chart file ID-suffixed
	_touch(tmp_path / "song_819.ini")
	_touch(tmp_path / "notes_454.chart")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "id_suffixed"
	assert "song_819.ini" in result["detail"]
	assert "notes_454.chart" in result["detail"]


def test_no_ini_when_folder_has_no_ini_file(tmp_path):
	_touch(tmp_path / "notes.chart")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "no_ini"


def test_no_ini_for_empty_folder_never_raises(tmp_path):
	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "no_ini"


def test_no_chart_file_when_ini_present_but_no_chart_or_mid(tmp_path):
	_touch(tmp_path / "song_2400.ini")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "no_chart_file"


def test_case_insensitive_literal_names_are_ok(tmp_path):
	# real library has seen wrong-case names from certain chart sources
	_touch(tmp_path / "Song.INI")
	_touch(tmp_path / "Notes.Chart")

	result = module.scan_song_folder_chart_names(tmp_path)

	assert result["status"] == "ok"

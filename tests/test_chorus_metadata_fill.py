"""fill_song_ini_metadata(): blank-only fill from a confident Chorus match.

Critically, a song.ini with an existing value for a fillable key must come
out byte-identical for that key even when Chorus returns something
different -- the pipeline's own output and any manual edits both take
priority over Chorus data.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_chorus_fill_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


KRYPTONITE_CHORUS_RESULT = {
	"name": "Kryptonite", "artist": "3 Doors Down", "album": "The Better Life",
	"genre": "Post-Grunge", "year": "1999", "charter": "Youngblood",
}


def _write_ini(folder, content):
	folder.mkdir(parents=True, exist_ok=True)
	(folder / "song.ini").write_text(content, encoding="utf-8", newline="")


def test_fills_blank_fields_from_confident_match(tmp_path):
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\n")

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=KRYPTONITE_CHORUS_RESULT):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "filled"
	content = (tmp_path / "song.ini").read_text(encoding="utf-8")
	assert "year = 1999" in content
	assert "genre = Post-Grunge" in content
	assert "album = The Better Life" in content
	assert "charter = Youngblood" in content


def test_never_overwrites_an_existing_value(tmp_path):
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\nyear = 2005\n")

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=KRYPTONITE_CHORUS_RESULT):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	content = (tmp_path / "song.ini").read_text(encoding="utf-8")
	assert "year = 2005" in content
	assert "year = 1999" not in content
	# other blank fields still get filled
	assert "genre = Post-Grunge" in content


def test_no_change_when_all_fillable_fields_already_present(tmp_path):
	_write_ini(
		tmp_path,
		"[Song]\nname = Kryptonite\nartist = 3 Doors Down\nyear = 2005\ngenre = Rock\ncharter = Me\nalbum = Test\n",
	)

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=KRYPTONITE_CHORUS_RESULT):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "no_change"


def test_error_when_no_song_ini(tmp_path):
	result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "error"


def test_error_when_song_ini_missing_name_or_artist(tmp_path):
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\n")

	result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "error"


def test_dry_run_touches_no_file(tmp_path):
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\n")
	original = (tmp_path / "song.ini").read_text(encoding="utf-8")

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=KRYPTONITE_CHORUS_RESULT):
		result = CH.fill_song_ini_metadata(str(tmp_path), dry_run=True)

	assert result["status"] == "filled"
	assert (tmp_path / "song.ini").read_text(encoding="utf-8") == original


def test_rejects_unsafe_chorus_field_but_fills_the_rest(tmp_path):
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\n")
	dirty_result = dict(KRYPTONITE_CHORUS_RESULT, genre="Rock [Explicit]")

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=dirty_result):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	content = (tmp_path / "song.ini").read_text(encoding="utf-8")
	assert "genre" not in content
	assert "year = 1999" in content

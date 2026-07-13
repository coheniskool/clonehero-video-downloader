"""Chorus match-confidence handling: no-match, ambiguous/low-confidence results.

Threshold is 70 (SequenceMatcher ratio*100 on name+artist, both required) --
lower than chart-rename's 85 since a wrong metadata fill is far less
destructive than a bad file rename, but still real: applying data from the
wrong song would corrupt this song's genre/year/charter/album.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_chorus_confidence_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


def _write_ini(folder, content):
	folder.mkdir(parents=True, exist_ok=True)
	(folder / "song.ini").write_text(content, encoding="utf-8", newline="")


def test_no_match_when_chorus_client_returns_none(tmp_path):
	_write_ini(tmp_path, "[Song]\nname = Some Obscure Song\nartist = Some Obscure Band\n")

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=None):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "no_match"


def test_no_match_when_best_result_is_a_different_song(tmp_path):
	# server's top fuzzy-match result is for a completely different song --
	# must not apply its data just because it was the only result returned
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\n")
	wrong_song = {"name": "Say It Ain't So", "artist": "Weezer", "year": "1994"}

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=wrong_song):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "no_match"
	assert "confidence" in result["detail"].lower()


def test_matches_at_exactly_the_threshold_boundary_case(tmp_path):
	# minor real-world formatting difference (e.g. "3 Doors Down" vs "3 Doors Down ")
	# should still clear the 70 threshold comfortably
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\n")
	close_enough = {"name": "Kryptonite", "artist": "3 Doors Down", "year": "1999"}

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=close_enough):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "filled"


def test_confidence_uses_the_weaker_of_name_and_artist_scores(tmp_path):
	# name matches perfectly but artist is completely different -- must not
	# average the two scores into a passing result
	_write_ini(tmp_path, "[Song]\nname = Kryptonite\nartist = 3 Doors Down\n")
	same_name_different_artist = {"name": "Kryptonite", "artist": "Some Cover Band", "year": "2010"}

	with patch.object(CH.chorus_client, "search_by_artist_title", return_value=same_name_different_artist):
		result = CH.fill_song_ini_metadata(str(tmp_path))

	assert result["status"] == "no_match"

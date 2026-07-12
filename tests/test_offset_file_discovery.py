"""find_song_audio/find_song_ini/find_video_file, both real naming conventions.

The real library at M:\\_Organized\\Songs mixes two chart-source naming
conventions in the same folder tree: plain names (song.ogg, song.ini) and
numeric-ID-suffixed names (song_1877.ogg, song_2400.ini) from a different
chart source. These functions must handle both without hardcoding exact
filenames, and must never match isolated stem tracks (guitar/drums/rhythm/
vocals/keys/crowd) as if they were the full backing mix.
"""

import clonehero_video_offset as module


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


# --- find_song_audio -------------------------------------------------------

def test_finds_plain_song_ogg_ignoring_stems(tmp_path):
	_touch(tmp_path / "song.ogg")
	_touch(tmp_path / "guitar.ogg")
	_touch(tmp_path / "drums_1.ogg")

	result = module.find_song_audio(tmp_path)

	assert result == tmp_path / "song.ogg"


def test_finds_id_suffixed_song_audio_ignoring_stems(tmp_path):
	_touch(tmp_path / "song_1877.ogg")
	_touch(tmp_path / "drums_183.ogg")
	_touch(tmp_path / "guitar_2051.ogg")
	_touch(tmp_path / "crowd_360.ogg")
	_touch(tmp_path / "rhythm_1315.ogg")
	_touch(tmp_path / "vocals_1237.ogg")

	result = module.find_song_audio(tmp_path)

	assert result == tmp_path / "song_1877.ogg"


def test_falls_back_to_sole_stem_when_no_full_mix_present(tmp_path):
	# real-library case: "12 Stones - Adrenaline" ships only guitar_546.opus,
	# no dedicated song*.ext full mix -- using the sole track is the only option
	_touch(tmp_path / "guitar_546.opus")

	result = module.find_song_audio(tmp_path)

	assert result == tmp_path / "guitar_546.opus"


def test_returns_none_for_multiple_stems_and_no_full_mix(tmp_path):
	_touch(tmp_path / "guitar.ogg")
	_touch(tmp_path / "drums_1.ogg")
	_touch(tmp_path / "vocals.ogg")

	result = module.find_song_audio(tmp_path)

	assert result is None


def test_returns_none_for_empty_folder_never_raises(tmp_path):
	result = module.find_song_audio(tmp_path)

	assert result is None


# --- find_song_ini -----------------------------------------------------------

def test_find_song_ini_prefers_literal_song_ini_name(tmp_path):
	_touch(tmp_path / "song.ini")

	result = module.find_song_ini(tmp_path)

	assert result == tmp_path / "song.ini"


def test_find_song_ini_matches_id_suffixed_name(tmp_path):
	_touch(tmp_path / "song_2400.ini")

	result = module.find_song_ini(tmp_path)

	assert result == tmp_path / "song_2400.ini"


def test_find_song_ini_returns_none_when_absent(tmp_path):
	result = module.find_song_ini(tmp_path)

	assert result is None


# --- find_video_file regression (already correct, locking in behavior) -----

def test_find_video_file_ignores_bak_cruft(tmp_path):
	_touch(tmp_path / "video.mp4.mkv.bak")

	result = module.find_video_file(tmp_path)

	assert result is None


def test_find_video_file_finds_exact_name_even_with_cruft_present(tmp_path):
	_touch(tmp_path / "video.mp4")
	_touch(tmp_path / "video.mp4.mkv.bak")

	result = module.find_video_file(tmp_path)

	assert result == tmp_path / "video.mp4"

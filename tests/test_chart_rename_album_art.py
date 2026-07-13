"""Album-art naming check and the .sng-container skip guard.

Album art needs a literal filename too (album.png/album.jpg/album.jpeg),
confirmed against the official wiki -- a real gap in this spec's original
scope. Real folders inspected 2026-07-14 show the same generating bug that
produces ID-suffixed song.ini/notes.chart/notes.mid also produces
ID-suffixed album art (Kryptonite: album_827.png, Mr. Roboto: album_822.jpg,
You Only Live Once: album_525.jpg). Unlike audio stems, zero candidates is a
valid, non-blocking outcome -- album art isn't hard-required.
"""

import clonehero_video_offset as module


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


# --- scan_song_folder_album_art ---------------------------------------------

def test_ok_when_album_art_is_literal_png(tmp_path):
	_touch(tmp_path / "album.png")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "ok"


def test_ok_when_album_art_is_literal_jpg(tmp_path):
	_touch(tmp_path / "album.jpg")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "ok"


def test_ok_when_no_album_art_present_at_all(tmp_path):
	# album art isn't hard-required -- zero candidates is a valid outcome
	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "ok"


def test_rename_candidate_for_real_kryptonite_album_art(tmp_path):
	_touch(tmp_path / "album_827.png")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "rename_candidate"
	assert "album_827.png" in result["detail"]


def test_rename_candidate_for_real_mr_roboto_album_art(tmp_path):
	_touch(tmp_path / "album_822.jpg")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "rename_candidate"


def test_needs_review_when_multiple_album_art_candidates(tmp_path):
	_touch(tmp_path / "album_111.png")
	_touch(tmp_path / "album_222.jpg")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "needs_review"


def test_needs_review_when_literal_and_id_suffixed_both_present(tmp_path):
	_touch(tmp_path / "album.jpg")
	_touch(tmp_path / "album_525.jpg")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "needs_review"


def test_ignores_unrelated_image_files(tmp_path):
	_touch(tmp_path / "background.png")
	_touch(tmp_path / "highway.png")

	result = module.scan_song_folder_album_art(tmp_path)

	assert result["status"] == "ok"


# --- is_sng_packaged ---------------------------------------------------------

def test_is_sng_packaged_true_when_sng_file_present(tmp_path):
	_touch(tmp_path / "song.sng")

	assert module.is_sng_packaged(tmp_path) is True


def test_is_sng_packaged_false_for_normal_folder(tmp_path):
	_touch(tmp_path / "song.ini")
	_touch(tmp_path / "notes.chart")

	assert module.is_sng_packaged(tmp_path) is False
